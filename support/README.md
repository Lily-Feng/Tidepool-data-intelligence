# Tidy

A support-agent prototype for a diabetes data platform. Tidy works a ticket queue
the way a support engineer would: it diagnoses with read-only tools, answers
from a knowledge base, escalates with evidence, and hands safety-related reports
straight to a human.

> **Synthetic data only.** Every account, ticket and log is generated. Tidy gives
> no medical advice. It is an independent project, not affiliated with Tidepool
> or any device maker.

- Architecture and portability: [docs/architecture.md](docs/architecture.md)
- The generic design it adapts: [docs/support-agent-design.md](docs/support-agent-design.md)
- Phase-by-phase results: [docs/engineering-log.md](docs/engineering-log.md)

## Layout

```text
support/
├── ports/       platform-neutral interfaces (LLM, Secrets, EventPublisher, …)
├── core/        config loading, quota limits; later the domain logic
├── adapters/
│   ├── local/   in-memory / file / Keychain adapters used by every test
│   └── gcp/     Gemini API, Secret Manager, … (the only place GCP SDKs appear)
├── app/         FastAPI service (Phase 0: /health, /ready)
├── targets/     which adapter backs each port: local, local-gemini, gcp-dev, record
├── scripts/     check_gemini_limits
└── infra/       bootstrap.sh, deploy.sh (GCP)
tests/support/   unit, contract and portability tests
```

## Run the tests

```bash
python -m venv .venv && .venv/bin/pip install -r support/requirements-dev.txt
.venv/bin/python -m pytest tests/support -q
```

Tests run offline against local adapters. Tests marked `gcp` call live services
and run only with `TIDY_RUN_GCP=1`.

## Use the live Gemini API from your Mac

```bash
python -m keyring set tidy gemini-api-key                 # paste the AI Studio key
python -m support.scripts.check_gemini_limits --no-call   # list models, check configured IDs
python -m support.scripts.check_gemini_limits             # + one request per configured model
```

Model IDs and client-side limits live in [targets/_gemini.yaml](targets/_gemini.yaml).
Callers ask for a role (`agent`, `support`, `judge`), never a model, so changing
models is a config change.

## Deploy to GCP

```bash
export TIDY_GCP_PROJECT=<project id> TIDY_BILLING_ACCOUNT=<billing account id>
bash support/infra/bootstrap.sh   # once: project, budget alerts, APIs, registry, identity, secret
bash support/infra/deploy.sh      # build from support/ only, deploy private Cloud Run, smoke test
```

The API key's own AI Studio project should stay without billing, which keeps it
on the free tier. Only the key value is copied into the Tidy project's Secret
Manager.

## Rules for contributors

- Business logic imports `support.ports`, never an adapter. Cloud SDKs only under
  `support/adapters/<cloud>/`. `tests/support/test_portability.py` enforces both.
- No identifiers in the repo: project IDs, billing accounts and keys come from the
  environment or a secret store.
- Recorded model responses (`eval/recordings/`) must come from synthetic prompts.
  Review them before committing.
