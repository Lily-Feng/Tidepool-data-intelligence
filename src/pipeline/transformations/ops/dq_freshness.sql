-- Ops: freshness and coverage per silver dataset, so a stalled collector shows up
-- as an old latest_event_utc instead of silently missing days. Counts and
-- timestamps only, no health values.
CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.${ops_schema}.dq_freshness
COMMENT 'Per silver dataset: rows, days covered, latest event time and hours since it.'
AS WITH datasets AS (
  SELECT 'cbg_events' AS dataset, source_system, count(*) AS row_count, count(DISTINCT local_date) AS days, max(event_time_utc) AS latest_event_utc FROM cbg_events GROUP BY source_system
  UNION ALL SELECT 'smbg_events', source_system, count(*), count(DISTINCT local_date), max(event_time_utc) FROM smbg_events GROUP BY source_system
  UNION ALL SELECT 'basal_intervals', source_system, count(*), count(DISTINCT local_date), max(interval_end_utc) FROM basal_intervals GROUP BY source_system
  UNION ALL SELECT 'bolus_events', source_system, count(*), count(DISTINCT local_date), max(event_time_utc) FROM bolus_events GROUP BY source_system
  UNION ALL SELECT 'carb_events', source_system, count(*), count(DISTINCT local_date), max(event_time_utc) FROM carb_events GROUP BY source_system
  UNION ALL SELECT 'pump_events', source_system, count(*), count(DISTINCT local_date), max(event_time_utc) FROM pump_events GROUP BY source_system
  UNION ALL SELECT 'site_changes', source_system, count(*), count(DISTINCT local_date), max(site_start_utc) FROM site_changes GROUP BY source_system
  UNION ALL SELECT 'settings_history', source_system, count(*), CAST(NULL AS BIGINT), max(valid_from_utc) FROM settings_history GROUP BY source_system
)
SELECT
  *,
  timestampdiff(HOUR, latest_event_utc, current_timestamp()) AS hours_since_latest_event,
  current_timestamp() AS as_of_utc
FROM datasets;
