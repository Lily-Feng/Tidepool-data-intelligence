# Data contract

## Contract goals

The contract must make source replay safe, preserve the original evidence, and
prevent a source-specific unit or schema assumption from silently changing
clinical measurements.

## Supported inputs

1. A historical Tidepool JSON export containing a top-level array of events
   (`src/ingest/tidepool_export.py`).
2. Later: incremental Tidepool API pulls, packaged the same way.
3. Later: Apple Health (Health Auto Export JSON) and lab results (CSV template
   or FHIR `Observation` JSON), each with its own source system folder.

Every channel converts its input into newline-delimited JSON before Lakeflow
ingestion. Each line contains one record plus an ingestion envelope. A channel
that delivers a different payload shape gets its own `source_contract_version`.

## Batch contract

The ingest script writes a batch locally (under git-ignored `private/raw/batches/`)
and uploads it to the Unity Catalog volume:

```text
/Volumes/<catalog>/private_raw/landing/<source_system>/<batch_id>/
  events.ndjson.gz
  manifest.json
```

`<source_system>` is `tidepool`, later `apple_health` or `labs`. Batches are
immutable and never deleted: they are what a full pipeline refresh rebuilds from.

The manifest contains no token or health measurements:

| Field | Type | Meaning |
|---|---|---|
| `batch_id` | string UUID | Unique immutable batch identifier. |
| `source` | string | Channel: `tidepool_export` (later `tidepool_api`, `tidepool_connector`, `apple_health_export`, `labs_manual`, `labs_fhir`). |
| `source_contract_version` | string | Parser and unit contract version. |
| `collector_version` | string | Ingest script version. |
| `retrieved_at_utc` | timestamp | When the batch was packaged. |
| `source_sha256` | string | Hash of the source export file; re-running the same export is a no-op. |
| `row_count` / `skipped_count` | long | Records written / records missing `id`, `type` or `time`. |
| `type_counts` | map | Records per event type. |
| `event_time_min_utc` / `event_time_max_utc` | timestamp | Event time range. |
| `content_sha256` | string | Hash of `events.ndjson.gz`. |
| `status` | string | `complete`. |

`events.ndjson.gz` is uploaded first and `manifest.json` last, so a manifest in
the volume means the batch is complete. Bronze reads only `events.ndjson.gz`.

## Raw event envelope

Each NDJSON record contains:

```json
{
  "batch_id": "synthetic-example",
  "retrieved_at_utc": "2026-01-01T00:00:00Z",
  "source": "tidepool_export",
  "source_contract_version": "tidepool-export-v1",
  "record_index": 0,
  "record_sha256": "...",
  "event_type": "cbg",
  "event_id": "...",
  "event_time": "2026-01-01T00:00:00Z",
  "event_json": "{...original event, unchanged...}"
}
```

`event_json` preserves the source event as a string, so Bronze has a fixed
schema regardless of event type and dotted keys like `bgTarget.high` need no
special handling. Silver parses only the fields it needs.

## Identity and deduplication

Raw identifiers stay in Bronze (`private_raw`). Silver drops `deviceId`,
`uploadId`, serial numbers and free text, and exposes:

- `subject_key`: a pseudonymous subject ID set by the bundle variable.
- `event_key`: `sha2(source_system | event_id | child_key)`, stable across
  replays and across channels of the same source system.

Stage 2 (sharing) replaces these with keyed HMAC and per-share keys before
anything leaves the private zone.

Deduplication rules:

1. Bronze never deduplicates.
2. Logical record identity is `(event_type, event_id, child_key)`, independent
   of channel, so an API pull overlapping an earlier export updates rather than
   duplicates. `child_key` is `''` except for exploded settings rows.
3. Exploded pump-setting rows (file export) share one `id` per snapshot; their
   `child_key` is `scheduleName | <segment>.start`. Never deduplicate settings
   on `id` alone.
4. `tidepool_events_current` (AUTO CDC, SCD type 1) keeps the version with the
   greatest `(retrieved_at_utc, record_sha256)`. A replayed older batch cannot
   overwrite newer content. Bronze keeps every version; `dq_event_conflicts`
   counts identities whose content changed between batches.
5. Reprocessing an identical batch or overlapping API window must not
   change Silver counts.

## Time contract

Store:

- `event_time_utc`: parsed from source `time`.
- `timezone_offset_minutes`: source offset when present.
- `event_time_local`: UTC plus the per-event offset.
- `ingested_at_utc`: Databricks ingestion time.
- `retrieved_at_utc`: collector retrieval time.

Use UTC for joins and ordering. Use local time for day boundaries, hour-of-day,
weekday, and dashboard calendar labels. Never derive local dates from one
fixed workspace timezone.

## Basal duration and rate contract

Tidepool documents basal `rate` as insulin units per hour and canonical basal
`duration` as milliseconds. A Twiist export instead contains
minute-like floating-point durations: approximately `4.9667` corresponds to
298 seconds between `time` and `payload.nextStateTime`.

Silver must retain:

| Field | Meaning |
|---|---|
| `rate_u_per_hour` | Source rate normalized to units/hour. |
| `duration_raw` | Exact source numeric value. |
| `duration_source_unit` | `minute`, `millisecond`, or `unknown`. |
| `duration_seconds` | Normalized duration. |
| `duration_rule` | Named rule selected from the source contract version. |
| `interval_end_utc` | Normalized interval end. |
| `delivered_basal_units` | `rate_u_per_hour * duration_seconds / 3600`. |

Unit selection happens at the source-contract or batch level, never from an
individual row's numeric magnitude.

For the current export contract:

```text
duration_seconds = duration_raw * 60
```

For canonical Tidepool millisecond data:

```text
duration_seconds = duration_raw / 1000
```

When `payload.nextStateTime` is available, compare it with the calculated end
time. A disagreement outside the configured tolerance produces a quality flag;
it must not be silently overwritten.

## Other duration and schedule rules (tidepool-export-v1)

| Field | Rule |
|---|---|
| `deviceEvent/pumpSettingsOverride.duration` | Minutes, like basal: `duration_seconds = duration * 60`. |
| `pumpSettings.*.<segment>.start` | A UTC timestamp on a reference date. Local schedule start minute = (UTC hour × 60 + minute + `timezoneOffset`) mod 1440, parsed from the string. |
| `deviceEvent/prime` with `primeTarget = cannula` | Starts an infusion site; a further cannula prime within 120 minutes is the same site. |
| `deviceEvent/timeChange.to` | Contains a time-zone name (coarse location); not carried past Bronze. |

## Embedded JSON and dotted fields

- Bronze preserves `payload` as received.
- Silver parses only an allowlist of known payload fields, initially
  `deliveredState`, `nextState`, and `nextStateTime`.
- Unknown payload fields remain accessible in restricted Bronze but do not
  automatically become app-visible columns.
- Flattened source columns such as `units.bg` and `bgTarget.high` are renamed in
  Silver to `bg_units` and `bg_target_high`.
- Free text, annotations, schedule names, and serial numbers are excluded from
  Gold unless a separate privacy review approves them.

## Silver shared columns

Every event-grain silver table, from any source system, carries:

```text
event_key, subject_key, source_system, event_time_utc, event_time_local,
timezone_offset_minutes, local_date, source_batch_id, source_record_hash
```

Span tables (`basal_intervals`, `site_changes`, later `sleep_sessions`) use
`*_start_utc` / `*_end_utc` in place of `event_time_utc`. No device, upload or
serial key is carried. Per-table columns are listed in
[data-engineering-design.md](data-engineering-design.md#72-entity-catalog).

## Gold five-minute contract

`gold.features_5m` has one row per `(subject_key, bucket_start_utc)`:

```text
subject_key
bucket_start_utc
bucket_start_local
glucose_value
glucose_units
glucose_age_seconds
basal_units_in_bucket
weighted_basal_rate_u_per_hour
bolus_units_in_bucket
carbs_in_bucket
delivered_state
glucose_delta_5m
glucose_delta_15m
glucose_mean_30m
glucose_stddev_60m
data_complete
quality_flags
feature_as_of_utc
```

Basal allocation uses interval overlap:

```text
basal_units_in_bucket =
  sum(rate_u_per_hour * overlap_seconds / 3600)
```

Do not join basal intervals to the nearest timestamp.

## Data-quality actions

| Condition | Action |
|---|---|
| Missing `id`, `type`, or `time` | Quarantine from Silver; retain in Bronze. |
| Malformed event JSON | Quarantine and alert. |
| Malformed embedded payload | Preserve raw, set flag, continue when core fields are valid. |
| Unknown event type | Preserve in Bronze and report; do not fail all ingestion. |
| Unknown source contract version | Stop Silver normalization for that batch. |
| Negative duration | Quarantine interval. |
| Basal rate outside documented range | Quarantine interval and alert. |
| Calculated end before start | Quarantine interval. |
| Repeated identical event | Keep Bronze copies; one Silver row. |
| Same event identity with conflicting content | Keep all Bronze copies; latest Silver row plus conflict flag. |
| Missing five-minute CGM bucket | Keep a missingness indicator; do not forward-fill indefinitely. |

## Schema evolution

- Bronze accepts new fields without losing them.
- Silver schemas are explicit and reviewed.
- New source fields first appear in an evolution report or rescued-data column.
- A contract-version change requires fixture updates, reconciliation tests, and
  a changelog entry before promotion.

## Reconciliation requirements

Every run records:

```text
manifest rows
Bronze rows by batch and type
Silver rows by type
duplicate rows removed from Silver
conflicting event versions
quarantine rows by reason
minimum and maximum event timestamps
pipeline completion and freshness timestamps
```
