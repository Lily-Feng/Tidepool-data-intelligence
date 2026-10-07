-- Ops: per-batch reconciliation. Manifest rows must equal bronze rows; the
-- current-state count shows how many records each batch still contributes after
-- later overlapping batches superseded it. Counts only, no health values.
CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.${ops_schema}.dq_batch_reconciliation
COMMENT 'Per batch: manifest rows vs bronze rows, and rows still current after deduplication.'
AS WITH bronze AS (
  SELECT batch_id, count(*) AS bronze_rows
  FROM ${catalog}.${raw_schema}.tidepool_events_raw
  GROUP BY batch_id
),
current_rows AS (
  SELECT batch_id, count(*) AS current_rows
  FROM ${catalog}.${raw_schema}.tidepool_events_current
  GROUP BY batch_id
)
SELECT
  m.batch_id,
  m.source,
  m.source_contract_version,
  m.retrieved_at_utc,
  m.event_time_min_utc,
  m.event_time_max_utc,
  m.row_count AS manifest_rows,
  coalesce(b.bronze_rows, 0) AS bronze_rows,
  coalesce(c.current_rows, 0) AS current_rows,
  m.row_count = coalesce(b.bronze_rows, 0) AS rows_match
FROM ${catalog}.${ops_schema}.ingest_manifests m
LEFT JOIN bronze b USING (batch_id)
LEFT JOIN current_rows c USING (batch_id)
WHERE m.source LIKE 'tidepool%';
