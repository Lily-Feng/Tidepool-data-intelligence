# TideTrack Studio V1 architecture

## System context

```text
Tidepool export / authorized API
            |
            v
Local collector
- retrieves an overlapping time window
- converts source arrays to NDJSON records
- creates checksum + manifest
- never logs token or health values
            |
            v
Private S3 raw bucket
- immutable source files
- SSE-KMS, versioning, Block Public Access
- collector write role
- Databricks read role
            |
            v
Unity Catalog external location / volume
            |
            v
Lakeflow Declarative Pipeline (triggered)
    |                 |                 |
    v                 v                 v
 Bronze             Silver             Gold
 raw events         typed facts        features_5m
 manifests          quarantine         daily_summary
                    settings history   dashboard datasets
                                            |
                                            v
                                   SQL warehouse
                                            |
                                            v
                                   Databricks AppKit app
```

## Environment model

| Environment | Data | Purpose |
|---|---|---|
| Local development | Synthetic fixtures and one protected validation export | Collector and contract tests. |
| Databricks demo | Synthetic only | Public screenshots, tutorials, and UI development. |
| Databricks private | Real personal data | Restricted ingestion, analysis, and private dashboard. |

Real data must not be copied into the demo environment.

## AWS object model

Use physically separate private and public buckets:

```text
tidetrack-private-<random-suffix>/
  staging/tidepool/batch_id=<uuid>/events.ndjson.gz
  staging/tidepool/batch_id=<uuid>/manifest.json
  raw/tidepool/batch_id=<uuid>/events.ndjson.gz
  raw/tidepool/batch_id=<uuid>/original_export.json.gz
  raw/tidepool/batch_id=<uuid>/manifest.json
  pipeline/checkpoints/
  pipeline/schema/
  quarantine/

tidetrack-public-demo-<random-suffix>/
  synthetic/
```

Object keys must not contain a person name, device ID, glucose value, or other
sensitive source value.

## Unity Catalog object model

### Private catalog

```text
tidetrack_private
  bronze
    ingestion_manifest
    tidepool_events_raw
  silver
    cbg_events
    basal_intervals
    bolus_events
    food_events
    dosing_decisions
    pump_settings_history
    event_quarantine
  gold
    features_5m
    daily_summary
    dashboard_kpis
    dashboard_timeline
    data_freshness
  ops
    pipeline_reconciliation
    quality_metrics
```

### Demo catalog

```text
tidetrack_demo
  synthetic
  gold
```

The demo catalog must have no dependency or lineage path to
`tidetrack_private`.

## Dataset types

Use one triggered Lakeflow Declarative Pipeline:

- `bronze.ingestion_manifest`: streaming table using Auto Loader over finalized manifests.
- `bronze.tidepool_events_raw`: streaming table using Auto Loader over immutable NDJSON files.
- Silver facts: materialized views over Bronze for parsing, normalization, and deterministic deduplication.
- Gold aggregates: materialized views over Silver using batch reads.
- `silver.event_quarantine`: persisted records that cannot be safely normalized.

Materialized views are intentional for V1. The data is small, and recomputing
Silver/Gold correctly after a corrected or replayed source record is more
important than minimizing every scan.

## Processing semantics

1. The collector requests an overlapping window rather than relying on an
   exact last-seen timestamp.
2. It writes and verifies both objects under `staging/`, copies the manifest to
   the final `raw/` batch, then copies the event object into `raw/` last.
3. The final event-object creation is the batch commit; the collector advances
   its local watermark only after that succeeds.
4. Auto Loader processes each finalized file exactly once at the file level.
5. Bronze keeps all source records, including repeated events from overlapping
   windows.
6. Silver chooses the current record by deterministic event key, source event
   time, retrieval time, and record hash.
7. Gold produces one row per subject and five-minute bucket.

## Table-format decision

V1 tables use Delta. Raw source files remain JSON/NDJSON and are not converted
into Iceberg at the landing boundary. If external Iceberg access becomes a
real requirement, publish a separate sanitized curated table in a later
version. Do not expose private masked tables through external table APIs.

## Application architecture

The V1 app is a read-only AppKit Analytics application:

```text
React/AppKit components
        |
config/queries/*.sql
        |
AppKit analytics plugin
        |
SQL warehouse
        |
tidetrack_private.gold tables
```

The app does not need Lakebase because it has no forms, annotations, saved
preferences, or other persistent write-back state.

## Deployment-as-code target

When implementation begins, evolve the repository toward:

```text
databricks.yml
resources/
  tidetrack.pipeline.yml
  tidetrack.app.yml
src/pipeline/
  01_bronze_events.sql
  10_silver_cbg.sql
  11_silver_basal.sql
  12_silver_bolus.sql
  20_gold_features_5m.sql
  21_gold_daily_summary.sql
app/
  client/
  config/queries/
  server/
  tests/
scripts/
  collect_tidepool.py
tests/
  fixtures/synthetic/
```

This is a target structure, not authorization to scaffold or deploy. Deployment
requires explicit confirmation of the Databricks profile and user consent.

## Authoritative external references

- [Tidepool developer portal](https://developer.tidepool.org/)
- [Tidepool data model](https://developer.tidepool.org/data-model/)
- [Tidepool API specifications](https://github.com/tidepool-org/TidepoolApi)
- [Databricks Auto Loader](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader)
- [Auto Loader with Unity Catalog](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/unity-catalog)
- [Unity Catalog managed tables](https://docs.databricks.com/aws/en/tables/managed)
- [Databricks Apps](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/)
