-- Silver: discrete pump events: overrides, reservoir changes, alarms, time changes.
-- Override duration follows the contract rule (tidepool-export-v1: minutes).
-- The time-change destination (a time-zone name, i.e. a coarse location) is dropped.
CREATE OR REFRESH MATERIALIZED VIEW pump_events (
  CONSTRAINT has_time EXPECT (event_time_utc IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT override_has_duration EXPECT (event_category <> 'override' OR duration_seconds > 0)
)
COMMENT 'Pump overrides, reservoir changes, alarms and time changes.'
AS WITH parsed AS (
  SELECT
    event_key, subject_key, source_system,
    event_time_utc, event_time_local, timezone_offset_minutes, to_date(event_time_local) AS local_date,
    CASE sub_type
      WHEN 'pumpSettingsOverride' THEN 'override'
      WHEN 'reservoirChange' THEN 'reservoir_change'
      WHEN 'alarm' THEN 'alarm'
      WHEN 'timeChange' THEN 'time_change'
    END AS event_category,
    sub_type,
    get_json_object(event_json, '$.alarmType') AS alarm_type,
    CASE WHEN sub_type = 'pumpSettingsOverride' AND source_contract_version = 'tidepool-export-v1'
      THEN CAST(get_json_object(event_json, '$.duration') AS DOUBLE) * 60 END AS duration_seconds,
    CASE WHEN get_json_object(event_json, "$['units.bg']") = 'mmol/L' THEN 18.01559 ELSE 1 END AS bg_factor,
    CAST(get_json_object(event_json, "$['bgTarget.low']") AS DOUBLE) AS bg_target_low_raw,
    CAST(get_json_object(event_json, "$['bgTarget.high']") AS DOUBLE) AS bg_target_high_raw,
    source_batch_id, source_record_hash
  FROM tidepool_events_conformed
  WHERE event_type = 'deviceEvent'
    AND sub_type IN ('pumpSettingsOverride', 'reservoirChange', 'alarm', 'timeChange')
)
SELECT
  event_key, subject_key, source_system,
  event_time_utc, event_time_local, timezone_offset_minutes, local_date,
  event_category, sub_type, alarm_type, duration_seconds,
  timestampadd(SECOND, CAST(duration_seconds AS BIGINT), event_time_utc) AS event_end_utc,
  round(bg_target_low_raw * bg_factor, 0) AS override_target_low_mg_dl,
  round(bg_target_high_raw * bg_factor, 0) AS override_target_high_mg_dl,
  source_batch_id, source_record_hash
FROM parsed;
