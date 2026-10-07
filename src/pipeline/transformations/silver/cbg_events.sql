-- Silver: CGM readings in mg/dL, one row per reading.
CREATE OR REFRESH MATERIALIZED VIEW cbg_events (
  CONSTRAINT has_time EXPECT (event_time_utc IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT plausible_glucose EXPECT (glucose_mg_dl BETWEEN 20 AND 600) ON VIOLATION DROP ROW
)
COMMENT 'CGM readings in mg/dL, one row per reading.'
AS SELECT
  event_key, subject_key, source_system,
  event_time_utc, event_time_local, timezone_offset_minutes, to_date(event_time_local) AS local_date,
  CASE get_json_object(event_json, '$.units')
    WHEN 'mg/dL' THEN CAST(get_json_object(event_json, '$.value') AS DOUBLE)
    WHEN 'mmol/L' THEN round(CAST(get_json_object(event_json, '$.value') AS DOUBLE) * 18.01559, 0)
  END AS glucose_mg_dl,
  source_batch_id, source_record_hash
FROM tidepool_events_conformed
WHERE event_type = 'cbg';
