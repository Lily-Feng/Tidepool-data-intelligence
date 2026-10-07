-- Bronze: every ingest record as received, in the restricted raw schema.
-- One row per source event per batch; never deduplicated here.
CREATE OR REFRESH STREAMING TABLE ${catalog}.${raw_schema}.tidepool_events_raw
COMMENT 'Tidepool events as received (envelope + original event JSON). Restricted.'
AS SELECT
  *,
  _metadata.file_path AS source_file,
  current_timestamp() AS ingested_at_utc
FROM STREAM read_files(
  '${landing_root}/tidepool/*/events.ndjson.gz',
  format => 'json',
  schema => 'batch_id STRING, retrieved_at_utc TIMESTAMP, source STRING, source_contract_version STRING,
             record_index BIGINT, record_sha256 STRING, event_type STRING, event_id STRING,
             event_time STRING, event_json STRING'
);
