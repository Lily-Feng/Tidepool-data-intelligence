# TideTrack Studio V1 implementation workstreams

## Dependency map

```text
W0 Foundation
   |\
   | \-> W1 Tidepool to S3
   |
   \----> W2 Unity Catalog foundation
              |
              v
         W3 S3 to Lakehouse
              |
              v
         W4 Gold dashboard data
              |
              v
         W5 Databricks App
              |
              v
         W6 Operational readiness
```

## W0 — Foundation and decisions

### Tasks

- [ ] Confirm an AWS account and region for the private S3 bucket.
- [ ] Confirm a Databricks AWS workspace that can use Unity Catalog external
      locations for real data.
- [ ] Reserve Databricks Free Edition for synthetic fixtures only.
- [ ] Confirm AppKit Analytics as the V1 app data-access choice.
- [ ] Confirm the 15-minute end-to-end freshness objective.
- [ ] Confirm official Tidepool API authorization and permitted development
      environment before automating production requests.
- [ ] Define retention: raw current objects, noncurrent S3 versions, logs, and
      derived tables.
- [ ] Create a privacy classification and access matrix.

### Pay attention to

- Tidepool asks application developers not to test against production without
  coordination; begin with an owned export and official API specifications.
- Do not make a Databricks profile choice automatically during implementation.
- Separate synthetic development from private real-data processing.

### Acceptance criteria

- Decisions D-01 through D-06 in the V1 overview are marked accepted.
- Named owners exist for AWS administration, Databricks administration, and
  data stewardship, even if one person holds all three roles.
- No real export is required to run unit or UI tests.

## W1 — Tidepool to S3

### W1.1 Secure AWS landing zone

- [ ] Create `tidetrack-private-<random-suffix>` without dots in the name.
- [ ] Enable S3 Block Public Access at account and bucket levels.
- [ ] Disable ACLs with Bucket Owner Enforced ownership.
- [ ] Configure SSE-KMS and a least-privilege KMS key policy.
- [ ] Deny non-TLS access in the bucket policy.
- [ ] Enable versioning and a bounded noncurrent-version lifecycle.
- [ ] Enable CloudTrail S3 data events.
- [ ] Create separate collector and Databricks IAM roles.
- [ ] Verify anonymous reads, collector reads, and collector deletes all fail.

### W1.2 Backfill collector

- [ ] Replace the placeholder export writer with a command that accepts an
      explicit protected source file.
- [ ] Validate that the source is a JSON array before processing.
- [ ] Preserve the original export as gzip-compressed immutable evidence.
- [ ] Convert events to `events.ndjson.gz` using the raw envelope contract.
- [ ] Create the manifest and checksum.
- [ ] Upload the manifest last.
- [ ] Implement `--dry-run` that performs validation without uploading.
- [ ] Make log output metadata-only: counts, batch ID, and timestamps.

### W1.3 Incremental API collector

- [ ] Pin the official Tidepool API contract and authentication flow being used.
- [ ] Store Tidepool credentials in a secret manager, not `.env` for deployed runs.
- [ ] Request an overlapping window to tolerate late records and updates.
- [ ] Add exponential backoff for retryable failures and no retry for invalid auth.
- [ ] Persist the watermark only after the manifest upload succeeds.
- [ ] Make each run safe to repeat.
- [ ] Batch events into one compressed NDJSON object per run; do not create one
      S3 object per five-minute event.

### W1 acceptance criteria

- The existing export is uploaded with matching checksum, row count, type
  counts, and event-time range.
- Re-running the same backfill creates either an explicit new batch version or
  exits idempotently; it never overwrites an existing raw object.
- A failed upload leaves no batch that appears complete.
- Tokens, device IDs, serial numbers, glucose values, and payloads do not appear
  in logs or S3 object names.

## W2 — Unity Catalog foundation

This workstream occurs before table creation, not after it.

### Tasks

- [ ] Create the `tidetrack_private` catalog and `bronze`, `silver`, `gold`, and
      `ops` schemas.
- [ ] Create a Unity Catalog storage credential backed by the Databricks S3 IAM
      role.
- [ ] Create a read-only external location or external volume over the raw S3 prefix.
- [ ] Create separate checkpoint/schema locations with only the permissions the
      pipeline requires.
- [ ] Bind private credentials and catalogs to the intended workspace when the
      account supports workspace bindings.
- [ ] Grant the pipeline identity read access to raw and create/modify access to
      its target schemas.
- [ ] Grant the app identity `SELECT` only on required Gold tables and `CAN_USE`
      on its SQL warehouse.
- [ ] Tag raw and identifier-bearing columns as health-sensitive.

### Pay attention to

- Prefer IAM role assumption through Unity Catalog; do not mount S3 with keys.
- Keep raw objects read-only to the pipeline.
- Do not grant the app access to Bronze or Silver.
- Use fully qualified names in tests and grants.

### W2 acceptance criteria

- Authorized pipeline identity can list/read raw objects.
- It cannot delete or overwrite raw objects.
- App identity can query approved Gold tables and cannot query Silver or Bronze.
- An unauthorized test principal cannot use the storage credential or catalog.

## W3 — S3 to Databricks lakehouse

### Recommended implementation

Use a SQL-first Lakeflow Declarative Pipeline deployed through a Declarative
Automation Bundle:

- Bronze streaming table with `STREAM read_files(...)` over the UC-governed raw
  path.
- Explicit Silver materialized views for domain parsing and deduplication.
- Gold materialized views for aggregation.
- Lakeflow expectations for quality reporting and quarantine routing.
- Triggered execution every 15 minutes rather than continuous compute.

### Tasks

- [ ] Scaffold a bundle only after selecting a Databricks CLI profile.
- [ ] Create the Bronze streaming table with ingestion metadata and rescued data.
- [ ] Parse the event envelope while preserving the original event.
- [ ] Create Silver CBG, basal, bolus, food, dosing-decision, and settings datasets.
- [ ] Implement the source-contract-specific duration rules.
- [ ] Implement deterministic deduplication and conflict flags.
- [ ] Route invalid rows into `silver.event_quarantine`.
- [ ] Create reconciliation and freshness outputs in `ops`.
- [ ] Add synthetic fixture and protected backfill integration tests.
- [ ] Validate, deploy, run, and poll the pipeline update to completion.

### Pay attention to

- Auto Loader schema inference treats untyped JSON conservatively; Silver must
  use explicit types.
- Use modern Lakeflow syntax, not legacy `LIVE` or `dlt` syntax.
- Do not aggregate a streaming source into an append-only streaming table;
  Gold aggregations are materialized views with batch reads.
- Do not use full refresh as a routine recovery mechanism.
- Changing a dataset from streaming table to materialized view later requires a
  new name or explicit migration.

### W3 acceptance criteria

- Bronze counts equal manifest counts for every complete batch.
- Silver replays are idempotent.
- The inspected export's duration values normalize from minutes to seconds and
  reconcile with `nextStateTime` within tolerance.
- Unknown contracts do not produce normalized Silver rows.
- All quality and reconciliation queries pass before promotion.

## W4 — Gold dashboard data

### Tasks

- [ ] Build `gold.features_5m` using interval-overlap basal allocation.
- [ ] Build `gold.daily_summary` using per-event local-calendar semantics.
- [ ] Build small, app-focused datasets for KPIs, timeline, and freshness.
- [ ] Define a configurable target-range source; do not bury clinical thresholds
      as unexplained SQL constants.
- [ ] Add date predicates and limit result sizes for app queries.
- [ ] Test missing CGM intervals, partial days, DST/offset changes, and empty periods.

### W4 acceptance criteria

- Basal units in five-minute buckets sum back to source interval totals within
  numeric tolerance.
- Daily metrics use local day boundaries.
- Every app metric has a written definition, unit, period, source table, and
  freshness field.
- App-facing query results remain well below the 1 MB event payload limit.

## W5 — Initial dashboard/App

### Tasks

- [ ] Confirm Analytics rather than Lakebase at the required decision gate.
- [ ] Discover and choose the SQL warehouse; do not hardcode its ID.
- [ ] Inspect the AppKit manifest and active scaffolding rules.
- [ ] Scaffold `tidetrack-dashboard` with the Analytics feature and `--run none`.
- [ ] Create parameterized SQL files before writing UI code.
- [ ] Run type generation and inspect generated query types.
- [ ] Implement the dashboard component plan in `dashboard-app-spec.md`.
- [ ] Implement loading, empty, error, and stale/partial states for every view.
- [ ] Declare the SQL warehouse and UC tables as app resources with permissions.
- [ ] Update Playwright smoke-test selectors from the generated defaults.
- [ ] Validate locally; deploy only after explicit user consent.

### W5 acceptance criteria

- The app loads without direct Bronze/Silver permissions.
- Date-range changes produce parameterized queries, not string-built SQL.
- No query returns raw event dumps or more than the app payload limit.
- Empty, failure, stale, and partial data are understandable to the user.
- KPI source and freshness are visible.
- The medical-information disclaimer is persistent but does not obscure data.

## W6 — Operational readiness

### Tasks

- [ ] Write runbooks for collector failure, pipeline failure, replay, credential
      rotation, and deletion requests.
- [ ] Alert on collector failure, missing manifest, pipeline failure, quarantine
      growth, and freshness SLA breach.
- [ ] Record collector, contract, pipeline, and app release versions.
- [ ] Rehearse recovery from a failed batch and an expired Tidepool credential.
- [ ] Review S3, KMS, Unity Catalog, warehouse, and app costs after a full week.
- [ ] Document how to rotate pseudonymization keys without breaking historical joins.

### W6 acceptance criteria

- A failed batch can be replayed without modifying raw source objects.
- A token and IAM role can be rotated without code changes.
- The owner can identify the last successful collector and pipeline runs.
- Raw and derived data can be deleted according to the documented retention policy.

## Suggested issue labels

```text
area/aws
area/tidepool
area/lakeflow
area/unity-catalog
area/app
area/security
area/data-contract
type/decision
type/implementation
type/test
type/runbook
```

