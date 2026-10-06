# Stage 1 plan — personal pipeline and app

Goal: one person (the owner, "user zero") can load their own Twiist/Tidepool and
Apple Health data into a lakehouse they control, see standard glucose metrics,
and ask questions of it. Code is open source; data stays private.

Stage 1 ends when three findings about the owner's own data hold up, each with
a number and enough days behind it. Phases end at a gate, not a date.

## Decisions to make first

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Where real data is processed | **Databricks Free Edition** for Stage 1 personal use, with ingest on the Mac and an encrypted raw copy kept locally. This supersedes the "no real data in Free Edition" rule in `docs/v1/` for personal, non-commercial use; keep the AWS/S3 Terraform as an optional hardened path. Revisit before anyone else's data is involved. |
| D2 | First source | Tidepool export backfill first, then the Export API, then Apple Health. |
| D3 | App surface | AI/BI dashboard + Genie space first; a custom Databricks App only if those fall short. |
| D4 | License | Apache-2.0 (patent grant, common for data tooling). |
| D5 | Public test data | A synthetic data generator in the repo; no real records in fixtures. |

Once D1 is settled, update `docs/v1/` to match so the repo has one source of truth.

## Phase 0 — Foundations

Build
- Repo hygiene: `.gitignore`, pre-commit hook, LICENSE, `CLAUDE.md` review rule.
- Check whether Free Edition can reach `api.tidepool.org`; if not, Mac-side ingest
  (expected).
- Mac ingest script: Tidepool export (file, then API with token in Keychain) →
  compressed NDJSON + manifest → upload to a Unity Catalog volume via Databricks CLI.
- Encrypted local raw archive (FileVault + encrypted backup).
- Unity Catalog: `private_raw`, `private_curated` schemas (and an empty
  `share_deid` placeholder for Stage 2), explicit grants.
- Synthetic data generator producing Tidepool-shaped events for tests and demos.

Gate: 90+ days of Tidepool data loaded; a re-run produces identical tables.

## Phase 1 — Pipeline and personal insight MVP

Build
- One Lakeflow declarative pipeline, daily batch: bronze → silver → gold.
- Pseudonymize at raw → curated: random subject ID, drop device serials, upload
  IDs, notes, free text; keep birth year only.
- Silver: CGM, basal intervals (fix minutes-vs-seconds duration), bolus, carbs,
  settings history, quarantine.
- Apple Health ingest (Health Auto Export JSON → volume): sleep stages, HR, HRV,
  workouts, steps; drop GPS routes.
- Gold: unified 5-minute timeline; daily metrics (TIR 70–180, TBR <70, CV, GMI,
  AGP by hour); event features (post-workout glucose, overnight range vs sleep and
  HRV, pre-bolus minutes, site-change day, day of week).
- AI/BI dashboard over gold: overview, timeline, data quality/freshness.
- Write down the five questions the data should answer; they drive the features.

Gate: three findings the owner did not know, each with a number and days of evidence.

## Phase 2 — AI analyst

Build
- Genie space over gold tables only.
- Weekly AI-written summary via `ai_query` on a workspace-hosted model (aggregates
  only; never raw traces to an outside model).
- One-page clinic report (patterns, never dosing instructions).
- Simple N-of-1 experiment tracking (intervention window vs baseline).

Gate: the care team finds the clinic report useful in a real visit.

## Proposed repo layout

```text
databricks.yml               # asset bundle
resources/                   # pipeline, jobs, dashboard, Genie definitions
src/pipeline/                # bronze/silver/gold SQL
src/ingest/                  # Mac-side Tidepool + Apple Health ingest
src/synthetic/               # synthetic data generator
tests/fixtures/synthetic/    # small synthetic samples only
infra/terraform/             # optional AWS path (*.example only)
private/                     # git-ignored
```

## Out of scope for Stage 1

De-identified sharing (Stage 2), multi-user packaging, dosing or setting
recommendations, real-time alerts, writing back to devices.
