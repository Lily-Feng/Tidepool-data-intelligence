"""Check which Gemini models the API key can call, and that configured IDs are right.

Lists the models visible to the key, flags configured model IDs that are not in
that list, then (unless --no-call) makes one tiny request per configured model.
That uses one request from each model's daily quota. Prints no key material.

Usage:
    python -m keyring set tidy gemini-api-key      # once
    python -m support.scripts.check_gemini_limits
    python -m support.scripts.check_gemini_limits --no-call
"""

from __future__ import annotations

import argparse
import sys

from support.core.config import Target
from support.ports.llm import LLMError, LLMRequest, Message, QuotaExhausted

PROBE = LLMRequest(role="probe", system="You are a connectivity check.",
                   messages=(Message("user", "Reply with the single word OK."),),
                   max_output_tokens=16)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", default="local-gemini")
    parser.add_argument("--no-call", action="store_true", help="list models only")
    args = parser.parse_args(argv)

    target = Target.load(args.target)
    section = target.section("llm")
    if section.get("adapter") != "gcp.gemini":
        print(f"target {args.target!r} does not use the Gemini adapter", file=sys.stderr)
        return 2
    llm = target.build("llm")

    visible = {name.removeprefix("models/"): actions for name, actions in llm.list_models()}
    text_models = sorted(m for m, acts in visible.items() if "generateContent" in acts)
    print(f"{len(text_models)} models support generateContent:")
    for m in text_models:
        print(f"  {m}")

    configured = section["models"]
    missing = [m for m in configured if m not in visible]
    print("\nConfigured models:")
    for model, limits in configured.items():
        flag = "MISSING from key's model list" if model in missing else "listed"
        print(f"  {model:32s} rpm={limits['rpm']:<3} rpd={limits['rpd']:<4} {flag}")

    if args.no_call:
        return 1 if missing else 0

    print("\nProbe calls (1 request each):")
    failed = bool(missing)
    for model in configured:
        if model in missing:
            continue
        try:
            r = llm.call_model(model, PROBE)
            print(f"  {model:32s} OK   tokens={r.input_tokens}+{r.output_tokens} "
                  f"latency={r.latency_ms}ms finish={r.finish_reason}")
        except (QuotaExhausted, LLMError) as exc:
            failed = True
            print(f"  {model:32s} FAIL {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
