-- Conformed envelope over current Tidepool records: the columns every silver
-- entity shares (keys, time, lineage), parsed once. Identifiers (deviceId,
-- uploadId, serials) are not carried forward; entities parse only the fields
-- they need from event_json. Pipeline-internal; not published.
CREATE TEMPORARY VIEW tidepool_events_conformed AS
SELECT
  sha2(concat_ws('|', 'tidepool', event_id, child_key), 256) AS event_key,
  '${subject_key}' AS subject_key,
  'tidepool' AS source_system,
  source AS source_channel,
  source_contract_version,
  event_type,
  get_json_object(event_json, '$.subType') AS sub_type,
  to_timestamp(event_time) AS event_time_utc,
  CAST(get_json_object(event_json, '$.timezoneOffset') AS INT) AS timezone_offset_minutes,
  timestampadd(MINUTE, CAST(get_json_object(event_json, '$.timezoneOffset') AS INT), to_timestamp(event_time)) AS event_time_local,
  event_json,
  batch_id AS source_batch_id,
  record_sha256 AS source_record_hash
FROM ${catalog}.${raw_schema}.tidepool_events_current;
