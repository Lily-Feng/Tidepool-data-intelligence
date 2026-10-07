-- One row per ingest batch manifest, any source. Manifests hold counts and
-- time ranges only, never health values, so this table lives in the ops schema.
-- The manifest is uploaded last, so a row here means the batch is complete.
CREATE OR REFRESH STREAMING TABLE ${catalog}.${ops_schema}.ingest_manifests
COMMENT 'Ingest batch manifests (counts, time ranges, hashes) for reconciliation and freshness.'
AS SELECT
  *,
  _metadata.file_path AS manifest_file,
  current_timestamp() AS ingested_at_utc
FROM STREAM read_files(
  '${landing_root}/*/*/manifest.json',
  format => 'json',
  multiLine => true,
  schema => 'batch_id STRING, source STRING, source_contract_version STRING, collector_version STRING,
             retrieved_at_utc TIMESTAMP, source_sha256 STRING, row_count BIGINT, skipped_count BIGINT,
             type_counts MAP<STRING, BIGINT>, event_time_min_utc TIMESTAMP, event_time_max_utc TIMESTAMP,
             content_sha256 STRING, status STRING'
);
