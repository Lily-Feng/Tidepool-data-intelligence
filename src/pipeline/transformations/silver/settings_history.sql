-- Silver: pump settings as versioned periods (slowly changing dimension, type 2).
-- Each upload repeats the full settings as a snapshot; the export explodes each
-- snapshot into one row per schedule segment. Identical consecutive snapshots
-- collapse into one version with valid_from/valid_to. Schedule names are free
-- text, so only a hashed schedule_key is kept.
-- settings_version is an ordinal that shifts if older history is loaded later;
-- join on valid_from_utc / valid_to_utc, not on the number.
CREATE OR REFRESH MATERIALIZED VIEW settings_history (
  CONSTRAINT known_contract EXPECT (source_contract_version = 'tidepool-export-v1') ON VIOLATION DROP ROW,
  CONSTRAINT has_value EXPECT (value IS NOT NULL AND value >= 0) ON VIOLATION DROP ROW
)
COMMENT 'Basal rates, carb ratios, sensitivities and targets per settings version, by time-of-day segment.'
AS WITH base AS (
  SELECT
    *,
    sha2(get_json_object(event_json, '$.scheduleName'), 256) AS schedule_key,
    get_json_object(event_json, '$.scheduleName') <=> get_json_object(event_json, '$.activeSchedule') AS is_active_schedule,
    CASE WHEN get_json_object(event_json, "$['units.bg']") = 'mmol/L' THEN 18.01559 ELSE 1 END AS bg_factor
  FROM tidepool_events_conformed
  WHERE event_type LIKE 'pumpSettings.%'
),
segments_raw AS (
  SELECT *, 'basal_rate' AS setting_type, 'U/h' AS unit,
    get_json_object(event_json, "$['basalSchedule.start']") AS start_raw,
    CAST(get_json_object(event_json, "$['basalSchedule.rate']") AS DOUBLE) AS value
  FROM base WHERE event_type = 'pumpSettings.basalSchedules'
  UNION ALL
  SELECT *, 'carb_ratio', 'g/U',
    get_json_object(event_json, "$['carbRatio.start']"),
    CAST(get_json_object(event_json, "$['carbRatio.amount']") AS DOUBLE)
  FROM base WHERE event_type = 'pumpSettings.carbRatios'
  UNION ALL
  SELECT *, 'insulin_sensitivity', 'mg/dL/U',
    get_json_object(event_json, "$['insulinSensitivity.start']"),
    round(CAST(get_json_object(event_json, "$['insulinSensitivity.amount']") AS DOUBLE) * bg_factor, 1)
  FROM base WHERE event_type = 'pumpSettings.insulinSensitivities'
  UNION ALL
  SELECT *, 'bg_target_low', 'mg/dL',
    get_json_object(event_json, "$['bgTarget.start']"),
    round(CAST(get_json_object(event_json, "$['bgTarget.low']") AS DOUBLE) * bg_factor, 0)
  FROM base WHERE event_type = 'pumpSettings.bgTargets'
  UNION ALL
  SELECT *, 'bg_target_high', 'mg/dL',
    get_json_object(event_json, "$['bgTarget.start']"),
    round(CAST(get_json_object(event_json, "$['bgTarget.high']") AS DOUBLE) * bg_factor, 0)
  FROM base WHERE event_type = 'pumpSettings.bgTargets'
),
segments AS (
  -- Export v1 writes segment start as a UTC timestamp whose time of day, plus the
  -- row's offset, is the local schedule start. Parsed from the string so the
  -- session time zone cannot shift it.
  SELECT
    *,
    event_time_utc AS snapshot_time_utc,
    pmod(CAST(substr(start_raw, 12, 2) AS INT) * 60 + CAST(substr(start_raw, 15, 2) AS INT)
         + coalesce(timezone_offset_minutes, 0), 1440) AS segment_start_minutes
  FROM segments_raw
),
snapshots AS (
  SELECT
    subject_key,
    snapshot_time_utc,
    sha2(array_join(array_sort(collect_list(concat_ws(':', setting_type, schedule_key,
      CAST(is_active_schedule AS STRING), CAST(segment_start_minutes AS STRING), CAST(value AS STRING)))), ','), 256) AS fingerprint
  FROM segments
  GROUP BY subject_key, snapshot_time_utc
),
versioned AS (
  SELECT
    *,
    sum(changed) OVER (PARTITION BY subject_key ORDER BY snapshot_time_utc ROWS UNBOUNDED PRECEDING) AS settings_version
  FROM (
    SELECT *,
      CASE WHEN fingerprint <=> lag(fingerprint) OVER (PARTITION BY subject_key ORDER BY snapshot_time_utc) THEN 0 ELSE 1 END AS changed
    FROM snapshots
  )
),
versions AS (
  SELECT
    subject_key, settings_version, valid_from_utc, snapshot_count,
    lead(valid_from_utc) OVER (PARTITION BY subject_key ORDER BY valid_from_utc) AS valid_to_utc
  FROM (
    SELECT subject_key, settings_version, min(snapshot_time_utc) AS valid_from_utc, count(*) AS snapshot_count
    FROM versioned
    GROUP BY subject_key, settings_version
  )
)
SELECT
  sha2(concat_ws('|', s.subject_key, CAST(v.valid_from_utc AS STRING), s.setting_type, s.schedule_key,
    CAST(s.segment_start_minutes AS STRING)), 256) AS settings_key,
  s.subject_key,
  s.source_system,
  v.settings_version,
  v.valid_from_utc,
  v.valid_to_utc,
  v.snapshot_count,
  s.setting_type,
  s.schedule_key,
  s.is_active_schedule,
  s.segment_start_minutes,
  coalesce(lead(s.segment_start_minutes) OVER (
    PARTITION BY s.subject_key, v.valid_from_utc, s.setting_type, s.schedule_key
    ORDER BY s.segment_start_minutes), 1440) AS segment_end_minutes,
  s.value,
  s.unit,
  s.source_contract_version,
  s.source_batch_id,
  s.source_record_hash
FROM segments s
JOIN versions v
  ON s.subject_key = v.subject_key AND s.snapshot_time_utc = v.valid_from_utc;
