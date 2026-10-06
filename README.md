# TideTrack Studio

A **privacy-first personal analytics tool** that helps diabetes users **get,
read, and analyze** their Tidepool CGM & insulin data. Not a medical device, not
a social platform — just clean data, well-engineered, presented clearly.

> **Informational personal analytics only — not medical advice.**

## Core Pipeline

```
Tidepool API → Collector → AWS S3 (encrypted) → Databricks Unity Catalog → Bronze → Silver → Gold → AI/BI App
```

| Layer | What It Does |
|-------|-------------|
| **Tidepool API → Collector** | Authenticates, pulls CGM/insulin/pump data; packages as NDJSON.gz with checksum + manifest |
| **S3 (Storage)** | SSE-KMS encryption, versioned, TLS-only, Block Public Access, CloudTrail audit |
| **Bronze** | Auto Loader streams raw JSON into Delta tables |
| **Silver** | Deduplicate, normalize units, quarantine bad records, split by event type |
| **Gold** | 5-min feature buckets, daily summaries, dashboard KPIs |
| **AI/BI App** | Read-only Databricks App with Overview, Timeline, and Data Quality tabs |

## What is included

- `scripts/` — starter ingestion script and secure token pattern
- `infra/terraform/` — AWS and Unity Catalog infrastructure (ready to `plan/apply`)
- `docs/v1/` — implementation-ready V1 architecture and specifications
- `docs/archive/` — deferred scope docs (agentic copilot, Apple Health, extended architecture)
- `github-pages/` — simple project landing page

## Getting started

1. Read the [V1 specification](docs/v1/README.md).
2. **Move real Tidepool exports outside this repository** (see Security below).
3. Provision the private S3 bucket and Unity Catalog via Terraform.
4. Backfill a protected export, then automate incremental API collection.
5. Build the Lakeflow Bronze → Silver → Gold pipeline.
6. Build the read-only AI/BI App against Gold tables.
7. Publish only code, documentation, schemas, and synthetic fixtures.

## Security

Real personal health data **must not** be committed to Git or stored in
Databricks Free Edition. Free Edition can be used for synthetic UI and pipeline
demonstrations. Keep real exports in the encrypted S3 bucket only.

## Workstreams

1. **Connector & Security** — Tidepool auth, collector script, S3 atomic commit, Terraform infra, secrets management
2. **Data Engineering** — Bronze/Silver/Gold DLT pipelines, deduplication, quarantine, ops tables
3. **AI/BI App** — Read-only dashboard with Overview, Timeline, and Data Quality tabs

## Deferred (not V1)

Agentic copilot · Apple Health streaming · Knowledge graph · Meal/activity
response joins · Multi-user tenancy · Predictive models · Mobile app ·
Write-back/annotations · Genie text-to-SQL

Archived docs for these features are in [`docs/archive/`](docs/archive/).

## Infrastructure quick start

Follow the [Terraform starter guide](infra/terraform/README.md) — it creates no
resources until you explicitly run `terraform apply`.
