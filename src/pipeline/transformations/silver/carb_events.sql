-- Silver: carbs only. The free-text meal name is dropped.
CREATE OR REFRESH MATERIALIZED VIEW carb_events (
  CONSTRAINT has_time EXPECT (event_time_utc IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT plausible_carbs EXPECT (carbs_g BETWEEN 0 AND 500) ON VIOLATION DROP ROW
)
COMMENT 'Carbohydrate entries in grams.'
AS SELECT
  event_key, subject_key, source_system,
  event_time_utc, event_time_local, timezone_offset_minutes, to_date(event_time_local) AS local_date,
  CAST(get_json_object(get_json_object(event_json, '$.nutrition'), '$.carbohydrate.net') AS DOUBLE) AS carbs_g,
  source_batch_id, source_record_hash
FROM tidepool_events_conformed
WHERE event_type = 'food';
