"""Tidy service entry point. Phase 0: health and readiness only.

Cloud Run reserves some paths ending in `z` (such as /healthz), so the probes
are /health and /ready.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Response

from support.core.config import Target
from support.ports.secrets import SecretNotFound

app = FastAPI(title="Tidy", description="Support-agent prototype. Synthetic data only; "
              "not affiliated with Tidepool.")


def _target_name() -> str:
    return os.environ.get("TIDY_TARGET", "local")


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up. Touches nothing external."""
    return {"status": "ok", "service": "tidy", "target": _target_name(),
            "git_sha": os.environ.get("GIT_SHA", "unknown")}


@app.get("/ready")
def ready(response: Response) -> dict:
    """Readiness: the target loads and the model API key secret is readable.

    Reports only whether each check passed, never secret values.
    """
    checks: dict[str, str] = {}
    try:
        target = Target.load(_target_name())
        checks["config"] = "ok"
        llm = target.section("llm")
        if "api_key_secret" in llm:
            target.build("secrets").get(llm["api_key_secret"])
            checks["llm_api_key"] = "ok"
    except SecretNotFound:
        checks["llm_api_key"] = "missing"
    except Exception as exc:  # report the failure class, not details that may hold identifiers
        checks["error"] = type(exc).__name__
    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "not_ready", "checks": checks}
