-- Silver: bolus deliveries.
CREATE OR REFRESH MATERIALIZED VIEW bolus_events (
  CONSTRAINT has_time EXPECT (event_time_utc IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT plausible_units EXPECT (delivered_units BETWEEN 0 AND 50) ON VIOLATION DROP ROW
)
COMMENT 'Bolus deliveries.'
AS SELECT
  event_key, subject_key, source_system,
  event_time_utc, event_time_local, timezone_offset_minutes, to_date(event_time_local) AS local_date,
  sub_type,
  CAST(get_json_object(event_json, '$.normal') AS DOUBLE) AS delivered_units,
  CAST(get_json_object(event_json, '$.expectedNormal') AS DOUBLE) AS expected_units,
  source_batch_id, source_record_hash
FROM tidepool_events_conformed
WHERE event_type = 'bolus';
