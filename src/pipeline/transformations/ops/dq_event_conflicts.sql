-- Ops: records whose content changed between batches (same identity, different
-- hash). A file export repeats one settings id across segment rows, so a conflict
-- means more distinct versions across batches than inside any one batch.
-- Counts only, no health values.
CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.${ops_schema}.dq_event_conflicts
COMMENT 'Count of Tidepool records that arrived with different content in different batches, by type.'
AS WITH per_batch AS (
  SELECT event_type, event_id, batch_id, count(DISTINCT record_sha256) AS versions_in_batch
  FROM ${catalog}.${raw_schema}.tidepool_events_raw
  GROUP BY event_type, event_id, batch_id
),
per_record AS (
  SELECT r.event_type, r.event_id, count(DISTINCT r.record_sha256) AS versions_total, max(p.versions_in_batch) AS max_versions_in_batch
  FROM ${catalog}.${raw_schema}.tidepool_events_raw r
  JOIN per_batch p USING (event_type, event_id, batch_id)
  GROUP BY r.event_type, r.event_id
)
SELECT event_type, count(*) AS conflicting_records
FROM per_record
WHERE versions_total > max_versions_in_batch
GROUP BY event_type;
