# Tidy engineering log

One entry per phase: what was built, the gate, what was measured. Counts and
costs only, no identifiers.

## Phase 0 — Foundation (in progress)

**Built**
- Ports: `LLM`, `Secrets`, `EventPublisher` (CloudEvents 1.0).
- Local adapters: scripted LLM, record/replay LLM, env and Keychain secrets,
  in-process publisher.
- GCP adapters: Gemini API (AI Studio key) with per-model RPM limiter, daily
  budget with batch reserve, per-minute retry, per-day exhaustion and role
  fallback; Secret Manager.
- Targets: `local`, `local-gemini`, `gcp-dev`, `record`, with shared Gemini
  settings in `_gemini.yaml`.
- Service: FastAPI `/health` and `/ready`; Dockerfile built from `support/` only.
- `scripts/check_gemini_limits.py`; `infra/bootstrap.sh` and `infra/deploy.sh`.
- CI: offline tests, portability rules, privacy scan.

**Gate**

| Check | Status |
|---|---|
| `pytest tests/support` green on the local target | ✅ 82 passed, 1 live test skipped |
| Configured model IDs confirmed and one live call per model | ⬜ needs the API key in Keychain, then `check_gemini_limits` |
| Cloud Run service deployed and private | ✅ `/health` 200 with identity token; unauthenticated call 403 |
| `/ready` OK (runtime identity reads the key secret) | 🟡 config OK; secret exists but has no version yet |
| Budget alerts in place before other APIs | ✅ $20 budget, alerts at $1 / $5 / $20 |

**Notes from the first bootstrap (2026-10-31)**
- Budget API calls bill their quota to the gcloud default project unless
  `--billing-project` is set; the script now always passes the Tidy project.
- Artifact Registry returned PERMISSION_DENIED right after the API was enabled;
  a rerun a minute later succeeded (propagation delay).
- Cloud Build: first build 48 s, from `support/` only. No Compute Engine API was
  needed.

**Free-tier limits observed (2026-10-30):** Flash Lite models 15 RPM, 250K TPM,
500 RPD; Flash models 5 RPM, 250K TPM, 20 RPD. Configured client-side at
12 / 4 RPM.
