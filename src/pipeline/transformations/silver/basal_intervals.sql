-- Silver: basal intervals.
-- Duration rule: contract tidepool-export-v1 carries basal duration in minutes
-- (docs/data-contract.md). Unknown contract versions are dropped, never guessed.
CREATE OR REFRESH MATERIALIZED VIEW basal_intervals (
  CONSTRAINT known_contract EXPECT (duration_rule IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT positive_duration EXPECT (duration_seconds > 0) ON VIOLATION DROP ROW,
  CONSTRAINT plausible_rate EXPECT (rate_u_per_hour BETWEEN 0 AND 35) ON VIOLATION DROP ROW
)
COMMENT 'Basal delivery intervals with normalized duration and delivered units.'
AS WITH parsed AS (
  SELECT
    event_key, subject_key, source_system,
    event_time_utc AS interval_start_utc,
    event_time_local AS interval_start_local,
    timezone_offset_minutes,
    get_json_object(event_json, '$.deliveryType') AS delivery_type,
    coalesce(CAST(get_json_object(event_json, '$.rate') AS DOUBLE), 0) AS rate_u_per_hour,
    CAST(get_json_object(event_json, '$.duration') AS DOUBLE) AS duration_raw,
    CASE source_contract_version WHEN 'tidepool-export-v1' THEN 'minutes_x60' END AS duration_rule,
    get_json_object(get_json_object(event_json, '$.payload'), '$.deliveredState') AS delivered_state,
    to_timestamp(get_json_object(get_json_object(event_json, '$.payload'), '$.nextStateTime')) AS next_state_time_utc,
    source_batch_id, source_record_hash
  FROM tidepool_events_conformed
  WHERE event_type = 'basal'
)
SELECT
  *,
  to_date(interval_start_local) AS local_date,
  timestampadd(MILLISECOND, CAST(duration_seconds * 1000 AS BIGINT), interval_start_utc) AS interval_end_utc,
  rate_u_per_hour * duration_seconds / 3600 AS delivered_units,
  abs(timestampdiff(SECOND, interval_start_utc, next_state_time_utc) - duration_seconds) > 30 AS end_time_mismatch
FROM (
  SELECT *, CASE duration_rule WHEN 'minutes_x60' THEN duration_raw * 60 END AS duration_seconds
  FROM parsed
);
