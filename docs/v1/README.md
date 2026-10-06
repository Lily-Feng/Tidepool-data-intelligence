# TideTrack Studio V1 specification

## Purpose

V1 proves that TideTrack can safely and repeatably move personal Tidepool data
into a governed Databricks lakehouse and present a useful read-only analytics
experience.

V1 is successful when one authorized user can:

1. Backfill an existing Tidepool export into private Amazon S3 storage.
2. Run an incremental collector without creating duplicate analytical events.
3. Ingest S3 files into Unity Catalog Bronze, Silver, and Gold Delta tables.
4. See fresh glucose and insulin history in a read-only Databricks App.
5. Re-run any failed batch without losing or corrupting source data.

This is an analytics and research tool. It does not provide medical advice,
recommend insulin dosing, or send instructions to a medical device.

## Correct implementation order

The original four goals are retained, but Unity Catalog must be provisioned
before tables are created:

1. Establish the security, AWS, Databricks, and Unity Catalog foundation.
2. Load Tidepool export/API batches into private S3.
3. Ingest S3 data into tables that are created directly in Unity Catalog.
4. Build the Gold dashboard datasets.
5. Build and validate the initial Databricks App.

There is no separate migration of legacy tables into Unity Catalog in V1.

## V1 documentation set

- [Architecture](architecture.md) — target components, boundaries, and object model.
- [Data contract](data-contract.md) — raw envelope, normalization, keys, units, and quality rules.
- [Implementation workstreams](workstreams.md) — actionable tasks, dependencies, and acceptance criteria.
- [Security and operations](security-operations.md) — raw-data protection, access, monitoring, recovery, and deletion.
- [Dashboard/App specification](dashboard-app-spec.md) — user questions, queries, layout, components, and UI states.

## Decisions required before coding

| ID | Decision | Recommended V1 choice | Why it matters |
|---|---|---|---|
| D-01 | Databricks environment for real data | AWS trial/paid workspace with Unity Catalog and private S3 access | Free Edition is appropriate only for synthetic demo data. |
| D-02 | Tidepool acquisition path | Existing export backfill first; official API integration second | Establishes a trusted baseline before API scheduling and authentication complexity. |
| D-03 | App data access | AppKit Analytics backed by a SQL warehouse | Best fit for read-only charts, KPIs, filters, and aggregations. |
| D-04 | Refresh objective | Collector every 5 minutes; S3 micro-batches and pipeline every 15 minutes | Preserves five-minute source resolution without always-on streaming overhead. |
| D-05 | Primary table format | Unity Catalog managed Delta | Best alignment with Lakeflow, materialized views, Feature Store, and MLflow. |
| D-06 | Public demonstration data | Fully synthetic data | Pseudonymized single-person medical history is not suitable for GitHub publication. |

### App data-access decision gate

Before the AppKit project is scaffolded, confirm one of these choices:

| | Lakebase synced tables | Analytics |
|---|---|---|
| Response pattern | Sub-second operational lookup | Warehouse query taking a few seconds |
| Best for | Typeahead, full-text search, lookup by ID | KPIs, charts, date filters, aggregations |
| V1 recommendation | No | **Yes** |

Adding annotations or other persistent user write-back would be a separate
Lakebase decision for a later version.

## Milestones

| Milestone | Outcome | Exit evidence |
|---|---|---|
| M0 — Foundation | Private AWS and Unity Catalog boundary exists | Security checklist and access tests pass. |
| M1 — Backfill | Existing export is preserved in S3 with a manifest | Checksum, row count, and event-time range match the source. |
| M2 — Incremental ingestion | Re-runnable Tidepool collector writes immutable batches | Replaying the same window changes no Silver event counts. |
| M3 — Lakehouse | Bronze, Silver, Gold, and quarantine objects exist in Unity Catalog | Table grants, lineage, quality counts, and reconciliation queries pass. |
| M4 — Dashboard data | Gold datasets answer the V1 user questions | Query contract tests and freshness checks pass. |
| M5 — App | Read-only AppKit dashboard works for the authorized user | Loading, empty, error, stale, accessibility, and smoke tests pass. |
| M6 — Operations | Failed batches can be diagnosed and replayed | Runbook rehearsal succeeds without editing raw objects. |

## Definition of done

- Raw files are absent from Git and cannot be read anonymously.
- No credential values appear in code, notebooks, logs, manifests, or object names.
- Every S3 batch has a unique ID, checksum, retrieval timestamp, and row count.
- Bronze preserves every source record and ingestion metadata.
- Silver deduplicates replayed events and records normalization provenance.
- The basal-duration unit discrepancy is explicitly handled and tested.
- Gold calculations use local-calendar semantics where appropriate and UTC for joins.
- The app reads only Gold tables through declared resources and least-privilege grants.
- Every KPI includes unit, period, source, and freshness.
- The app visibly labels its results as informational analytics, not medical advice.
- A documented procedure exists for replay, credential rotation, and data deletion.

## Deferred beyond V1

- Genie or natural-language querying.
- Predictive models and Model Serving.
- Vector search.
- Automated insulin recommendations or device control.
- Multi-user tenancy.
- Annotations, forms, or other write-back workflows.
- Couchbase or Lakebase operational state.
- Superset and Lightdash integrations.
- Iceberg publication for external engines.

