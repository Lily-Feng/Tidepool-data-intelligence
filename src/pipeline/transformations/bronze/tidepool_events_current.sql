-- Current state of every Tidepool record: one row per logical record, latest
-- retrieved version wins. Overlapping or repeated batches (export, API pulls
-- with lookback) upsert here instead of piling up. Restricted: still carries
-- identifiers and the full event JSON, so it lives next to bronze.
--
-- Record identity is (event_type, event_id, child_key). child_key separates the
-- rows a file export explodes out of one settings snapshot (same id, one row
-- per schedule segment); it is '' for every other record.
CREATE TEMPORARY VIEW tidepool_events_keyed AS
SELECT
  *,
  CASE WHEN event_type LIKE 'pumpSettings.%' THEN concat_ws('|',
    get_json_object(event_json, '$.scheduleName'),
    coalesce(
      get_json_object(event_json, "$['basalSchedule.start']"),
      get_json_object(event_json, "$['carbRatio.start']"),
      get_json_object(event_json, "$['insulinSensitivity.start']"),
      get_json_object(event_json, "$['bgTarget.start']")))
  ELSE '' END AS child_key
FROM STREAM(${catalog}.${raw_schema}.tidepool_events_raw);

CREATE OR REFRESH STREAMING TABLE ${catalog}.${raw_schema}.tidepool_events_current
COMMENT 'Latest version of each Tidepool record across all batches. Restricted.';

CREATE FLOW tidepool_events_current_cdc AS AUTO CDC INTO ${catalog}.${raw_schema}.tidepool_events_current
FROM STREAM(tidepool_events_keyed)
KEYS (event_type, event_id, child_key)
SEQUENCE BY STRUCT(retrieved_at_utc, record_sha256)
STORED AS SCD TYPE 1;
