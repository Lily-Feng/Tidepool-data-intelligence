# TwiistLab

A privacy-first personal analytics pipeline for people with type 1 diabetes.
It joins pump and CGM data (Twiist via Tidepool) — and later Apple Health — in a
Databricks lakehouse you own, so you can see *why* glucose does what it does.

> **Informational personal analytics only — not medical advice or a dosing
> recommendation.**

## How it works

```text
Tidepool export ──▶ src/ingest (your Mac) ──▶ UC volume  private_raw/landing/<source>/
                                                   │
               Lakeflow pipeline (on file arrival) ▼
               private_raw.tidepool_events_raw      (bronze, as received)
               private_raw.tidepool_events_current  (latest version of each record)
               private_curated.*                    (silver, identifiers dropped)
               private_analytics.daily_*            (gold, TIR / CV / GMI / insulin)
               private_ops.dq_*                     (reconciliation, freshness)
                                                   │
                                                   ▼
                                     AI/BI dashboard, Genie (planned)
```

Your data never goes through this repository. The repo holds code; the ingest
script uploads data straight from your machine to your own workspace.

## Quick start

Requires the [Databricks CLI](https://docs.databricks.com/dev-tools/cli/) and a
workspace (Free Edition works for personal use) with a configured profile.

```bash
# 1. Deploy schemas, volume, pipeline and refresh job
databricks bundle deploy -t dev            # dev: synthetic data, user-prefixed schemas

# 2. Try it with synthetic data
python src/synthetic/generate_tidepool.py --days 14 --out /tmp/synthetic.json
python src/ingest/tidepool_export.py /tmp/synthetic.json --out-dir /tmp/batches --upload \
    --volume /Volumes/twiistlab/dev_<your-user>_private_raw/landing

# 3. Run the pipeline
databricks bundle run -t dev tidepool
```

For your real data, deploy with `-t personal`, keep exports in the git-ignored
`private/raw/`, and upload with the default `--volume`.

## Repository layout

| Path | Contents |
|---|---|
| `databricks.yml`, `resources/` | Bundle: schemas, volume, pipeline, daily job |
| `src/ingest/` | Packages a Tidepool export into a batch and uploads it |
| `src/pipeline/transformations/` | Bronze / silver / gold SQL, one dataset per file |
| `src/synthetic/` | Synthetic Tidepool-shaped data for tests and demos |
| `tests/` | `python -m pytest tests` |
| `docs/` | Stage 1 plan, data engineering design, data contract, dashboard spec |

## Contributing safely

Never commit real health data, identifiers or secrets. Install the guard hook
once per clone: `git config core.hooksPath scripts/git-hooks`.
