# Data engineering design

How TwiistLab turns passively collected health data (pump, CGM, wearable, lab
results) into tables that answer questions about glucose, and keeps them current
as new data arrives. Covers sources and channels, the catalog layout, continuous
delivery, the medallion layers, data quality, and build order.

Related: [data-contract.md](data-contract.md) (batch format, envelope, unit
rules) · [dashboard-spec.md](dashboard-spec.md) · [stage1-plan.md](stage1-plan.md)

Status legend: ✅ built · 🟡 partial · ⬜ planned

---

## 1. Design approach: start from the questions

Tables are derived from the questions the owner wants answered, not from the
shape of a source. This keeps the model small and every table justified.

| Question | Needs | Sources |
|---|---|---|
| What moves time in range? | Daily metrics joined to daily context (weekday, site age, overrides, sleep, workouts) | Tidepool, Apple Health |
| How does glucose response vary across the day and week? | Glucose by hour of day; meal and correction windows | Tidepool |
| Did a settings change help? | Settings history as versioned periods; before/after comparison | Tidepool |
| Why was a specific night bad? | A 5-minute timeline aligning glucose, insulin, carbs, heart rate, sleep | Tidepool, Apple Health |
| Does exercise or poor sleep change the next day? | Event windows after workouts; daily sleep joined to next-day metrics | Tidepool, Apple Health |
| Does lab A1c agree with CGM-estimated GMI? | Lab results as periods compared with the CGM window before each draw | Labs, Tidepool |

These needs produce four gold shapes: **timeline**, **daily**, **event windows**
and **periods**. Every upstream table exists to feed one of them, and every new
source attaches to these shapes rather than adding a new one.

### Principles

1. **Grain first.** Every table states what one row represents. Most analysis
   errors are grain errors (double counting, mixing per-day and per-reading rows).
2. **Raw is immutable.** Landing files and bronze keep every record as received;
   everything downstream is reproducible from them.
3. **Idempotent by construction.** Loading the same data twice, or overlapping
   time ranges, never changes a silver count. Deduplication is keyed, not hoped for.
4. **Silver is by entity, not by source.** A silver table describes a real-world
   thing (a glucose reading, a sleep session, a lab result) and carries
   `source_system`, so a second source of the same thing is a new branch, not a
   new table.
5. **Identifiers stop at the raw schema.** Silver and gold carry only
   pseudonymous keys.
6. **UTC for joins, local time for meaning.** Days, hours and weekdays use the
   per-event local offset, never a fixed workspace time zone.
7. **Missing is not zero.** Gaps stay visible; nothing is interpolated or
   forward-filled into analysis tables.
8. **Descriptive only.** Gold describes what happened. No table computes a dose,
   setting or recommendation.

---

## 2. Sources and channels

A **source system** is where the data originates (Tidepool, Apple Health, a lab).
A **channel** is how it reaches the lakehouse (a file export, an API pull, a
connector). Channels differ in transport only: every channel writes the same
batch format into the landing volume, so the pipeline sees one shape per source
system regardless of how the data got there.

| Source system | Data | Channel | `source` value | Cadence | Status |
|---|---|---|---|---|---|
| Tidepool | CGM, pump (basal, bolus, carbs, device events, settings) | File export from Tidepool web app → `src/ingest/tidepool_export.py` | `tidepool_export` | Manual backfill | ✅ |
| Tidepool | same | Tidepool data API pull from the Mac, scheduled | `tidepool_api` | Daily | ⬜ |
| Tidepool | same | In-workspace connector (Python data source in a job task), only if the workspace can reach Tidepool | `tidepool_connector` | Daily | ⬜ optional |
| Apple Health | Sleep, workouts, heart rate, HRV, steps, (later) menstrual cycle | Health Auto Export JSON → Mac folder → ingest script | `apple_health_export` | Daily | ⬜ |
| Labs | A1c, lipids, kidney/thyroid panels, ketones | CSV template filled by hand, or FHIR `Observation` JSON from a patient portal / Apple Health clinical records | `labs_manual`, `labs_fhir` | A few times a year | ⬜ |

### Why every channel lands files

An in-workspace connector could write straight into bronze, but landing files
first keeps three properties for every channel:

- **Replay.** A full refresh rebuilds every table from files in the volume; no
  channel's history lives only in a streaming checkpoint.
- **One ingestion path.** One Auto Loader stream per source system; adding a
  channel adds no pipeline code unless the payload shape differs.
- **One reconciliation.** Every batch has a manifest, so counts are checked the
  same way for every channel.

### Channel differences are contract versions

When a channel delivers a different payload shape, it gets its own
`source_contract_version`, and silver parses by that version. Expected example:
the Tidepool file export flattens nested fields (`basalSchedule.start`, one row
per schedule segment) and carries basal duration in minutes; the Tidepool API
returns nested objects (one `pumpSettings` record with schedules inside) and
canonical millisecond durations. Both land in `tidepool_events_raw`; silver
entities choose the parsing rule by `source_contract_version`, and an unknown
version is dropped and counted, never guessed.

Records from different channels that describe the same datum share the Tidepool
`id`, so the current-state step (section 4) treats an API pull that overlaps an
earlier export as an update, not a duplicate.

---

## 3. Catalog and schema design

One catalog per deployment target (`twiistlab`; `dev` schemas are user-prefixed
by bundle development mode). Schemas split by **layer and sensitivity**, so a
grant on a schema is a grant on exactly one kind of data.

| Schema | Holds | Contains identifiers? | Readers |
|---|---|---|---|
| `private_raw` | Landing volume; bronze `*_raw` streaming tables; `*_current` current-state tables | Yes | Pipeline only |
| `private_curated` | Silver: typed, pseudonymized entities from all sources | No | Gold, ad-hoc analysis notebooks |
| `private_analytics` | Gold: timeline, daily, windows, periods | No | Dashboard, Genie space, findings notebooks |
| `private_ops` | Ingest manifests, reconciliation, freshness, conflict counts | No, and no health values | Dashboard data-quality page, alerts |

Why gold has its own schema: the Genie space and dashboard are pointed at
`private_analytics` only, so they never see per-reading silver rows or lineage
columns.

### Naming

| Layer | Pattern | Examples |
|---|---|---|
| Landing | `landing/<source_system>/<batch_id>/` | `landing/tidepool/…`, `landing/apple_health/…`, `landing/labs/…` |
| Bronze | `<source_system>_<payload>_raw` | `tidepool_events_raw`, `apple_health_records_raw`, `lab_results_raw` |
| Current state | `<source_system>_<payload>_current` | `tidepool_events_current` |
| Silver | entity noun; `_events` for instants, `_intervals`/`_sessions` for spans | `cbg_events`, `basal_intervals`, `sleep_sessions`, `lab_results` |
| Gold | analysis shape | `features_5m`, `daily_summary`, `meal_windows`, `settings_periods` |
| Ops | `ingest_*`, `dq_*` | `ingest_manifests`, `dq_freshness` |

### Code layout

One pipeline, one dataset per file, file named after the dataset:

```text
src/pipeline/transformations/
  bronze/   <source>_*_raw.sql, <source>_*_current.sql, ingest_manifests.sql
  silver/   <source>_events_conformed.sql (temporary view), one file per entity
  gold/     one file per analysis table
  ops/      dq_*.sql
```

One pipeline rather than one per source: gold joins across sources (glucose ×
sleep), and at personal scale a single triggered serverless update is simpler to
run and reason about. Split per source only if one source's refresh becomes slow
enough to delay the others.

---

## 4. Continuous delivery: how new data flows through

### 4.1 End-to-end

```text
Mac (launchd, daily)                         Databricks
────────────────────                         ──────────────────────────────────────────────
collector per source                         Job "refresh": file-arrival trigger on landing/
  pull window = [watermark − lookback, now]     (waits 5 min after last file, at most hourly)
  package batch: events.ndjson.gz + manifest            │
  upload events, then manifest ──────────▶   landing/<source>/<batch_id>/
  advance local watermark                               │
                                                        ▼
                                             Pipeline update (triggered, serverless)
                                               bronze   Auto Loader: only new files     append
                                               current  AUTO CDC, SCD 1 on record key   upsert
                                               silver   materialized views              refresh
                                               gold     materialized views              refresh
                                               ops      reconciliation, freshness       refresh
```

The job also runs on demand (`databricks bundle run refresh`) for manual exports.
In the `dev` target, bundle development mode deploys the trigger paused.

### 4.2 When a new time range arrives

Suppose batch A (an export) covers days 1–60 and batch B (an API pull) covers
days 55–75.

1. **Landing.** B is a new folder; nothing in A is touched. Batches are immutable.
2. **Bronze.** Auto Loader tracks processed files in its checkpoint and reads
   only B's `events.ndjson.gz`. Bronze now holds days 55–60 twice. That is by
   design: bronze is the evidence of what each batch said.
3. **Current state.** `tidepool_events_current` upserts B's records by
   `(event_type, event_id, child_key)`, sequenced by
   `(retrieved_at_utc, record_sha256)`. Days 55–60 records that are unchanged
   overwrite themselves; records the device re-uploaded with corrections win
   because B was retrieved later; new days 61–75 insert. A replayed or
   out-of-order older batch cannot overwrite newer content, because the
   sequence key is older.
4. **Silver.** Entity tables are materialized views over the current state.
   Serverless refreshes them incrementally where the query allows (row-level
   filters and projections) and recomputes where it does not (window functions
   in `site_changes`, `settings_history`). Either way the result equals a
   from-scratch computation.
5. **Gold.** Daily tables recompute; the days touched by B change, others stay
   identical. Windows and periods that straddle the old boundary (a site that
   started on day 59, a settings version that began on day 50) are correct
   because they are computed over the whole current state, not per batch.
6. **Ops.** `dq_batch_reconciliation` shows B's manifest rows = bronze rows and
   how many of A's rows are still current; `dq_freshness` moves the latest event
   time forward.

### 4.3 Collector rules (passive collection)

| Rule | Why |
|---|---|
| Pull by event time with a **lookback** (default 7 days before the watermark), weekly a 30-day re-pull | Pumps and phones upload late; a record for Tuesday can reach Tidepool on Friday. Overlap is free because the current-state step deduplicates. |
| Watermark = max event time of the last complete batch, stored locally under `private/` | The collector is restartable; a failed run simply re-pulls the same window. |
| Skip packaging when the source content hash matches a previous batch | Re-running an unchanged export is a no-op before it reaches the volume. |
| Upload events first, manifest last | A manifest in the volume means the batch is complete. |
| Tokens from macOS Keychain; logs show counts and batch IDs only | Secrets and health values never reach logs. |

### 4.4 Corrections, deletions and replays

| Situation | Behavior |
|---|---|
| Source corrects a record (same id, new content) | Later batch wins in current state; `dq_event_conflicts` counts it. |
| Source deletes a record | Not propagated in Stage 1 (exports and API pulls carry no tombstones). If it matters, a full re-export plus a rebuild of current state from that batch is the remedy; noted as an open question. |
| Parser bug fixed in silver | Redeploy; materialized views recompute from current state. No re-ingest. |
| Contract-version change | New version string in the collector, a new parsing branch in silver, fixtures and tests updated before the `personal` deploy. |
| Bronze schema change or corrupted checkpoint | Full refresh of the pipeline (owner-approved): rebuilds bronze and current state from landing files. Landing files are never deleted, which is what makes this safe. |

### 4.5 Cost and refresh mode

Triggered updates, not continuous: data changes at most daily, so a continuous
pipeline would idle at a cost. Personal volumes are small (tens of thousands of
records per quarter), so a full recompute of every materialized view finishes in
minutes; incremental refresh is an optimization, never a correctness
requirement.

---

## 5. Conventions

| Topic | Rule |
|---|---|
| Keys | `subject_key` (bundle variable); `event_key = sha2(source_system | source id | child_key)`, stable across replays and channels; no device, upload or serial IDs past `private_raw` |
| Shared silver columns | Every event-grain silver table has `event_key, subject_key, source_system, event_time_utc, event_time_local, timezone_offset_minutes, local_date, source_batch_id, source_record_hash` |
| Time columns | `*_utc` for instants, `*_local` for wall-clock; spans use `*_start_*` / `*_end_*` |
| Local day | `local_date = to_date(event_time_local)`; the pipeline pins `spark.sql.session.timeZone = UTC` so this never shifts; days with a time change may have 23 or 25 hours |
| Ordinals | `site_number`, `settings_version` are display ordinals that shift if older history loads later; joins use stable keys or time bounds |
| Glucose | mg/dL everywhere (mmol/L × 18.01559 when a source uses it) |
| Insulin | Units (U); basal rates in U/hour; delivered basal = rate × seconds / 3600 |
| Carbs | Grams |
| Labs | Value in the unit the conformed table declares per test (e.g. A1c %), original unit kept; tests identified by LOINC code |
| Lineage | Every silver row carries `source_batch_id` and `source_record_hash` |
| Thresholds | Consensus CGM ranges (70–180, <70, <54, >180, >250 mg/dL), defined once and labeled as consensus targets |

---

## 6. Bronze and current state

| Table | Schema | Grain | Status | Notes |
|---|---|---|---|---|
| `tidepool_events_raw` | `private_raw` | One source record per batch | ✅ | Streaming table, Auto Loader on `landing/tidepool/*/events.ndjson.gz`. Fixed 10-column envelope; original record as `event_json` text. Never deduplicated. |
| `tidepool_events_current` | `private_raw` | One row per logical record | ✅ | AUTO CDC (SCD type 1) from bronze. Key `(event_type, event_id, child_key)`; `child_key` separates exported settings rows that share one id (schedule name + segment start), `''` otherwise. |
| `ingest_manifests` | `private_ops` | One row per batch, any source | ✅ | Auto Loader on `landing/*/*/manifest.json`. |
| `apple_health_records_raw` / `_current` | `private_raw` | One record per batch / per natural key | ⬜ | Same envelope. Health Auto Export records have no stable id, so `event_id = sha2(metric, start, end, source device name)`. |
| `lab_results_raw` / `_current` | `private_raw` | One result per batch / per result | ⬜ | `event_id` = FHIR `Observation.id`, or `sha2(test code, collected date)` for manual CSV. |

The current-state table replaces a "latest row per key" window over all of
bronze. It is incremental (each update processes only new bronze rows), and it is
the one place where cross-batch identity is decided.

---

## 7. Silver: one table per real-world entity

### 7.1 Two steps

1. **Conformed envelope** (temporary view per source, e.g.
   `tidepool_events_conformed`): computes the shared columns once (keys, UTC and
   local time, lineage) and drops identifiers. Not published.
2. **Entity tables** (materialized views in `private_curated`): filter the
   conformed view by record type, parse an allowlist of fields by contract
   version, normalize units, apply expectations.

### 7.2 Entity catalog

Tidepool (current scope):

| Table | Source records | Grain | Status | Key columns beyond the shared set |
|---|---|---|---|---|
| `cbg_events` | `cbg` | One CGM reading | ✅ | `glucose_mg_dl` |
| `smbg_events` | `smbg` | One fingerstick reading | ✅ | `glucose_mg_dl`, `sub_type` |
| `basal_intervals` | `basal` | One delivery interval | ✅ | `interval_start/end_utc`, `rate_u_per_hour`, `duration_raw`, `duration_rule`, `duration_seconds`, `delivered_units`, `delivery_type`, `delivered_state`, `end_time_mismatch` |
| `bolus_events` | `bolus` | One bolus | ✅ | `delivered_units`, `expected_units`, `sub_type` |
| `carb_events` | `food` | One carb entry | ✅ | `carbs_g` (meal name dropped) |
| `site_changes` | `deviceEvent/prime`, target `cannula` | One infusion site | ✅ | `site_key`, `site_number`, `site_start_utc/local`, `site_end_utc` (next site start), `site_hours`, `prime_count`. Primes within 120 min collapse into one site. |
| `pump_events` | `deviceEvent` subtypes `pumpSettingsOverride`, `reservoirChange`, `alarm`, `timeChange` | One event | ✅ | `event_category`, `alarm_type`, `duration_seconds`, `event_end_utc`, `override_target_low/high_mg_dl`. Time-change destination (a time-zone name) dropped. |
| `settings_history` | `pumpSettings.*` (basal schedules, carb ratios, sensitivities, targets) | One schedule segment per settings version | ✅ | `settings_key`, `settings_version`, `valid_from_utc`, `valid_to_utc`, `setting_type`, `schedule_key` (hashed name), `is_active_schedule`, `segment_start/end_minutes`, `value`, `unit` |

Planned, other sources (same shared columns, `source_system` set accordingly):

| Table | Source | Grain | Notes |
|---|---|---|---|
| `sleep_sessions` | Apple Health | One sleep stage interval | `stage` (awake, core, deep, REM, in bed), start/end; a night = sessions grouped by wake date |
| `workouts` | Apple Health | One workout | `activity_type`, start/end, `energy_kcal`, `avg_heart_rate`; GPS routes dropped at ingest |
| `health_samples` | Apple Health | One sample of a numeric metric | Long table: `metric_code` (heart_rate, hrv_sdnn, resting_heart_rate, steps, …), `value`, `unit`, start/end. New metrics are new codes, not new tables. |
| `lab_results` | Labs | One test result | `loinc_code`, `test_name`, `value`, `unit`, `value_normalized`, `reference_low/high`, `collected_at_utc`; free-text comments dropped |

Two table styles, deliberately: **wide entity tables** where the record has
structure that analysis depends on (basal intervals, sessions, workouts), and one
**long sample table** for sources with many simple numeric metrics, so Apple
Health's long tail of types does not create a table each.

**Not modeled:** `dosingDecision` records in current exports carry only unit
labels, with no forecast or recommendation values. `upload` records stay in bronze.

### 7.3 Problems silver must solve

| Problem | Rule |
|---|---|
| **Overlapping batches** | Resolved before silver by the current-state table. Re-running any batch must not change silver counts. |
| **Time zones and daylight saving** | Local time = UTC + per-record offset. Offsets change within a dataset (DST, travel); `time_change` pump events mark them. Never derive local dates from one fixed zone. |
| **Duration units** | Chosen by `source_contract_version`, never by value magnitude. Export v1: basal and override durations in minutes. Basal is cross-checked against `payload.nextStateTime`; disagreements over 30 s are flagged. |
| **Suspended delivery** | Intervals with no rate are rate 0, kept so gaps in delivery are visible. |
| **Embedded and dotted JSON** | `payload` and `nutrition` arrive as JSON strings; dotted keys (`bgTarget.low`) are read with bracket paths. Only an allowlist of fields is parsed. |
| **Settings are snapshots, not changes** | Each upload repeats the full settings. A snapshot fingerprint (hash of all segments) collapses identical consecutive snapshots into versions with `valid_from`/`valid_to` (SCD type 2, computed rather than streamed, because the source sends snapshots, not changes). |
| **Settings segment start** | Export v1 writes it as a UTC timestamp on a reference date; local start minute = UTC time of day + the row's offset, parsed from the string so the session zone cannot shift it. |
| **Repeated primes** | A re-prime within 120 minutes is the same site. |
| **Privacy** | Drop device, upload and serial IDs, free text (meal names, notes, schedule names), time-zone names, GPS routes. |

### 7.4 Adding a source or entity (the extension recipe)

1. **Collector** under `src/ingest/`: writes the batch format into
   `landing/<source_system>/`, with a new `source` and `source_contract_version`.
2. **Synthetic generator** under `src/synthetic/` and tests: same shapes,
   invented values. This is the only data the `dev` target and tests use.
3. **Bronze** `<source>_*_raw.sql` (Auto Loader) and `<source>_*_current.sql`
   (AUTO CDC on the source's natural key).
4. **Conformed view** `<source>_*_conformed.sql`: shared columns.
5. **Entity tables**: add a branch to an existing entity if the thing already
   exists (a second CGM source → `cbg_events` union), otherwise a new entity file.
6. **Gold**: attach to an existing shape (new columns in `features_5m` or
   `daily_summary`, a new window table, a new period table).
7. **Ops**: extend `dq_batch_reconciliation` and `dq_freshness`.
8. **Contract and this document**: add the source's rules.

---

## 8. Gold: four analysis shapes (`private_analytics`)

### 8.1 Timeline: `features_5m` ⬜ (the backbone)

**Grain:** one row per subject per 5-minute bucket, 288 per local day, including
buckets with no data.

| Column group | Columns |
|---|---|
| Time | `bucket_start_utc`, `bucket_start_local`, `local_date`, `hour_local`, `weekday` |
| Glucose | `glucose_mg_dl` (nearest reading within the bucket), `cgm_present`, `glucose_delta_15m`, `glucose_mean_30m` |
| Insulin | `basal_units` (overlap-allocated), `bolus_units`, `delivery_state` |
| Carbs | `carbs_g` |
| Context | `site_key`, `site_age_hours`, `override_active`, `settings_version` |
| Apple Health (later) | `heart_rate`, `steps`, `sleep_stage`, `in_workout` |

- Basal is allocated by interval overlap with the bucket, never by nearest timestamp.
- The grid is generated from a calendar (all buckets per day) left-joined to
  facts, so empty buckets exist.
- Missing CGM stays null; no forward fill.

### 8.2 Daily: `daily_summary` 🟡

**Grain:** one row per subject per local day. Currently split across
`daily_glucose` ✅ and `daily_insulin_carbs` ✅; merge into `daily_summary` with
context.

| Column group | Columns |
|---|---|
| Glucose | `readings`, `cgm_coverage_pct`, `mean_mg_dl`, `tir_pct` (70–180), `tbr_70_pct`, `tbr_54_pct`, `tar_180_pct`, `tar_250_pct`, `cv_pct`, `gmi_pct` |
| Insulin and carbs | `basal_units`, `bolus_units`, `total_units`, `carbs_g` |
| Context | `weekday`, `is_weekend`, `site_day` (1, 2, 3…), `override_minutes`, `alarm_count`, `settings_version` |
| Apple Health (later) | `sleep_minutes`, `deep_sleep_minutes`, `workout_minutes`, `steps`, `resting_heart_rate`, `hrv_sdnn` (prior night) |
| Quality | `valid_day` (coverage ≥ 70%), `partial_day` |

GMI = 3.31 + 0.02392 × mean mg/dL. CV = 100 × stddev / mean.

### 8.3 Event windows ⬜ (where the insight is)

**Grain:** one row per event, summarizing the glucose curve around it.

| Table | Window | Columns |
|---|---|---|
| `meal_windows` | −30 to +240 min around each carb entry | `glucose_start`, `glucose_peak`, `rise_mg_dl`, `minutes_to_peak`, `glucose_2h`, `glucose_3h`, `prebolus_minutes`, `meal_period`, `site_day`, `overlapping_meal` flag |
| `overnight_windows` | 00:00–06:00 local each night | `tir_pct`, `min_glucose`, `lows_count`, `cv_pct`, `bedtime_glucose`, `late_carbs_g` (after 21:00); later `sleep_minutes`, `hrv_sdnn` |
| `site_windows` | Each infusion site's lifetime | `site_hours`, TIR by site day, `occlusion_alarms` |
| `override_windows` | Each override, plus 2 h after | Glucose during and after, `override_minutes` |
| `correction_windows` | Bolus with no carbs within ±30 min | Glucose start, +2 h, +4 h |
| `workout_windows` (later) | Workout start to +24 h | Glucose during, nadir, lows in the following night |

Windows overlapping another meal or with under 70% CGM coverage are flagged
rather than dropped, so analysis can filter explicitly.

### 8.4 Periods ⬜

| Table | Grain | Purpose |
|---|---|---|
| `settings_periods` | One row per settings version | Date range, days covered, that period's TIR, TBR, CV, mean glucose. "What changed after the change?" as a description, not a judgment of the settings. |
| `lab_periods` (later) | One row per lab result | The result plus CGM metrics over the matching window before the draw (A1c: 90 days; GMI vs A1c). |

---

## 9. Data quality and operations

| Where | Check | Table |
|---|---|---|
| Ingest | Manifest `row_count` = bronze rows per batch | `private_ops.dq_batch_reconciliation` ✅ |
| Current state | Records whose content changed between batches, by type | `private_ops.dq_event_conflicts` ✅ |
| Freshness | Rows, days covered and hours since latest event per silver table | `private_ops.dq_freshness` ✅ |
| Silver | Expectations drop impossible values (glucose outside 20–600 mg/dL, basal rate outside 0–35 U/h, bolus outside 0–50 U, carbs outside 0–500 g, non-positive durations, unknown contract versions); dropped counts are in the pipeline event log | event log |
| Silver | Basal end-time mismatch flagged, not overwritten; overrides without a duration warned | columns / event log |
| Gold | `features_5m` basal summed over buckets equals interval totals (tolerance 0.001 U) | ⬜ |
| Gold | Every metric carries its day or event count and coverage | ⬜ |
| Analysis | A finding needs ≥ 14 days with ≥ 70% CGM coverage (consensus minimum) | — |

Ops tables hold counts and timestamps, never health values, so the dashboard's
data-quality page can be shown without exposing readings. A later alert on
`dq_freshness.hours_since_latest_event` (for example > 48 h for CGM) catches a
stalled collector; it is an ops alert about data arrival, not a health alert.

Tests run against synthetic data (`src/synthetic/`) so they can live in the
public repo. The generator can cut overlapping export windows from one history
(`--window`) to exercise incremental loads in `dev`.

---

## 10. From tables to insight

Analysis climbs three steps:

1. **Describe:** AGP (5th/25th/50th/75th/95th glucose percentiles by hour of
   day), TIR trend, daily insulin and carbs.
2. **Stratify:** compare groups within the owner's own history, e.g. TIR by site
   day; meal rise by pre-bolus bucket (0, 1–10, >10 min); breakfast vs dinner;
   weekday vs weekend; overnight TIR with and without late carbs; next-day TIR
   after short vs normal sleep.
3. **Experiment (N-of-1):** baseline period vs intervention period (for example
   a post-dinner walk), compared with day counts shown.

Rules for anything reported as a finding:
- State the number, the days or events behind it, and the spread.
- Check for confounding (for example, site day 3 coinciding with weekends) and
  regression to the mean after unusually bad periods.
- Describe patterns ("rise was lower when bolused more than 10 minutes before
  eating, n = …"), never instructions ("change your carb ratio").

---

## 11. Build order

| Step | Deliverable | Unlocks |
|---|---|---|
| 1 ✅ | Current-state table, conformed view, silver `site_changes`, `pump_events`, `settings_history`, `smbg_events`; ops reconciliation and freshness; file-arrival job | Site age, overrides, settings versions; continuous loading |
| 2 | First `dev` deploy with two overlapping synthetic windows; check reconciliation, then `personal` | Proof that incremental loads are idempotent |
| 3 | Tidepool API collector with watermark + lookback, scheduled by launchd | Passive daily collection |
| 4 | Gold `features_5m` + basal reconciliation test | The backbone for everything below |
| 5 | Gold `daily_summary` with context; `meal_windows`; `overnight_windows` | First stratified findings |
| 6 | AI/BI dashboard (incl. data-quality page from `private_ops`); Genie space over `private_analytics` | Plain-English questions |
| 7 | Apple Health collector, bronze/current, `sleep_sessions`, `workouts`, `health_samples`; columns in `features_5m` and `daily_summary` | The pump + wearable join |
| 8 | `site_windows`, `override_windows`, `correction_windows`, `settings_periods` | Deeper comparisons |
| 9 | Labs collector (CSV template, then FHIR), `lab_results`, `lab_periods` | A1c vs GMI |

## 12. Open questions

- Meaning of each basal `deliveredState` value (closed-loop pattern vs override
  vs open loop) needs confirming against Twiist documentation before it drives
  any metric.
- Whether the Tidepool API returns the same `id` and the same values as the file
  export for the same datum (assumed; check on the first API batch with
  `dq_event_conflicts`), and its exact shape for settings and durations (expected
  to be a new contract version).
- Settings snapshots: confirm all four `pumpSettings.*` rows of one upload share
  the same `time` (the fingerprint groups by it) and that segment starts do not
  shift across a DST change.
- Deletions at the source: whether Tidepool ever removes data that a later pull
  should remove here.
- Whether file-arrival triggers on volumes are available on the Free Edition
  workspace; fallback is a daily schedule on the same job.
