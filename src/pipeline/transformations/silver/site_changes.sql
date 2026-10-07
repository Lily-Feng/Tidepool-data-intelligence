-- Silver: infusion sites. One row per site, from cannula primes. A prime within
-- 120 minutes of the previous one is a re-prime of the same site, not a new site.
-- site_key (the first prime's event_key) is stable; site_number is an ordinal that
-- shifts if older history is loaded later, so join on site_key.
CREATE OR REFRESH MATERIALIZED VIEW site_changes
COMMENT 'Infusion sites: start, end (next site start) and age, from cannula prime events.'
AS WITH primes AS (
  SELECT
    *,
    lag(event_time_utc) OVER (PARTITION BY subject_key ORDER BY event_time_utc) AS prev_prime_utc
  FROM tidepool_events_conformed
  WHERE event_type = 'deviceEvent' AND sub_type = 'prime'
    AND get_json_object(event_json, '$.primeTarget') = 'cannula'
),
numbered AS (
  SELECT
    *,
    sum(CASE WHEN prev_prime_utc IS NULL OR timestampdiff(MINUTE, prev_prime_utc, event_time_utc) > 120 THEN 1 ELSE 0 END)
      OVER (PARTITION BY subject_key ORDER BY event_time_utc ROWS UNBOUNDED PRECEDING) AS site_number
  FROM primes
),
sites AS (
  SELECT
    subject_key,
    source_system,
    site_number,
    min_by(event_key, event_time_utc) AS site_key,
    min(event_time_utc) AS site_start_utc,
    min_by(event_time_local, event_time_utc) AS site_start_local,
    count(*) AS prime_count,
    max_by(source_batch_id, event_time_utc) AS source_batch_id
  FROM numbered
  GROUP BY subject_key, source_system, site_number
)
SELECT
  *,
  to_date(site_start_local) AS local_date,
  lead(site_start_utc) OVER (PARTITION BY subject_key ORDER BY site_start_utc) AS site_end_utc,
  round(timestampdiff(MINUTE, site_start_utc,
    lead(site_start_utc) OVER (PARTITION BY subject_key ORDER BY site_start_utc)) / 60.0, 1) AS site_hours
FROM sites;
