# TideTrack Studio V1 data contract

## Contract goals

The contract must make source replay safe, preserve the original evidence, and
prevent a source-specific unit or schema assumption from silently changing
clinical measurements.

## Supported V1 inputs

1. A historical Tidepool JSON export containing a top-level array of events.
2. Incremental authorized API responses normalized by the collector.

The collector converts both into newline-delimited JSON before Lakeflow
ingestion. Each line contains one event plus an ingestion envelope.

## Raw S3 batch contract

Every batch directory contains:

```text
events.ndjson.gz
manifest.json
original_export.json.gz   # backfill batches only
```

The manifest contains no token or health measurements:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `batch_id` | string UUID | yes | Unique immutable batch identifier. |
| `source` | string | yes | `tidepool_export` or `tidepool_api`. |
| `source_contract_version` | string | yes | Parser and unit contract version. |
| `collector_version` | string | yes | Build identifier for the collector. |
| `retrieved_at_utc` | timestamp | yes | Retrieval completion time. |
| `requested_start_utc` | timestamp | API only | Requested window start. |
| `requested_end_utc` | timestamp | API only | Requested window end. |
| `row_count` | long | yes | Number of NDJSON event records. |
| `event_time_min_utc` | timestamp | yes when nonempty | Earliest source event. |
| `event_time_max_utc` | timestamp | yes when nonempty | Latest source event. |
| `content_sha256` | string | yes | Hash of the compressed event object. |
| `status` | string | yes | `complete`; incomplete batches remain under staging. |

Write files to a temporary local name and calculate the checksum. Upload and
verify both objects under a non-ingest `staging/` prefix. Publish the manifest
to the final `raw/` batch first, then copy the event object into `raw/` last.
The atomic creation of the final event object is the batch commit. Advance the
collector watermark only after it succeeds. Incomplete staging objects are
removed by a bounded lifecycle rule and are never scanned by Auto Loader.

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
  "event": {}
}
```

The `event` object is preserved without renamed, removed, or converted source
fields in Bronze.

## Identity and deduplication

Raw identifiers remain restricted. Silver exposes deterministic private keys:

- `subject_key`
- `device_key`
- `event_key`
- `upload_key`

Generate these with keyed HMAC, not an unsalted hash. The key lives in a secret
manager and is versioned separately from the data.

Deduplication rules:

1. Bronze never deduplicates.
2. Most event types use `(source, type, id)` as the logical event identity.
3. If the same logical identity has different content, retain the conflict in
   Bronze and select the latest retrieved version in Silver while recording a
   conflict quality flag.
4. Exploded pump-setting rows use a composite child key such as
   `(id, schedule_name, schedule_start)`; do not globally deduplicate settings
   on `id` alone.
5. Reprocessing an identical S3 object or overlapping API window must not
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
`duration` as milliseconds. The inspected TideTrack export instead contains
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

## Silver domain schemas

### `silver.cbg_events`

Required columns:

```text
event_key, subject_key, device_key, event_time_utc, event_time_local,
timezone_offset_minutes, glucose_value, glucose_units, upload_key,
source_batch_id, source_record_hash, ingested_at_utc, quality_flags
```

### `silver.basal_intervals`

Required columns:

```text
event_key, subject_key, device_key, interval_start_utc, interval_end_utc,
event_time_local, timezone_offset_minutes, delivery_type, rate_u_per_hour,
duration_raw, duration_source_unit, duration_seconds, duration_rule,
delivered_basal_units, delivered_state, next_state, next_state_time_utc,
upload_key, source_batch_id, source_record_hash, quality_flags
```

### `silver.bolus_events`

Required columns:

```text
event_key, subject_key, device_key, event_time_utc, event_time_local,
sub_type, delivered_units, expected_units, upload_key, source_batch_id,
source_record_hash, quality_flags
```

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
