# TideTrack Studio V1 security and operations specification

## Security objective

Protect raw and derived personal health data against accidental publication,
credential compromise, unauthorized analysis, and unrecoverable deletion while
keeping the pipeline simple enough for one owner to operate.

This document is a technical control baseline, not a legal compliance claim.

## Data classes

| Class | Examples | Permitted locations |
|---|---|---|
| Restricted raw | Original exports, device IDs, upload IDs, serial numbers, annotations | Encrypted local storage, private S3, restricted UC Bronze |
| Restricted derived | Pseudonymized event facts, exact timestamps, glucose and insulin history | Private UC Silver/Gold |
| Operational metadata | Batch IDs, row counts, checksums, run status | Private S3 manifests, UC Ops, monitoring |
| Public synthetic | Invented events with no lineage to real records | Git, demo catalog, public site |

## Prohibited locations

Real raw or derived records must not appear in:

- Git commits or Git history.
- GitHub Issues, pull requests, Actions logs, or build artifacts.
- Databricks Free Edition.
- Public S3 buckets or website prefixes.
- Notebook source, cell output, query names, resource names, or application logs.
- Slack, email, screenshots, or documentation examples.
- Public AI prompts or external model requests without a separate review.

## AWS controls

### Bucket

- S3 Block Public Access enabled at account and bucket levels.
- Bucket Owner Enforced ownership; ACLs disabled.
- SSE-KMS default encryption with a customer-managed key.
- Bucket policy denies non-TLS requests.
- Bucket policy permits only named roles and expected prefixes.
- Versioning enabled.
- Noncurrent-version expiration explicitly configured.
- CloudTrail data events enabled for object reads, writes, and deletes.
- IAM Access Analyzer reviewed after policy changes.

Do not put personal information into bucket names, object keys, tags, or KMS
aliases. These values can be exposed in administrative metadata and logs.

### IAM role matrix

| Principal | Raw list/read | Raw write | Raw delete | Curated write |
|---|---:|---:|---:|---:|
| Collector role | no | yes, new objects only | no | no |
| Lakeflow role | yes | no | no | yes, pipeline prefixes only |
| App service principal | no | no | no | no |
| Human data owner | emergency only | emergency only | controlled | controlled |

The app service principal receives Unity Catalog table access, never direct S3
raw access.

The collector may read only its own `staging/` objects when required to verify
or copy them. It receives no `GetObject` permission on finalized `raw/` data.

## Local controls

- Store real exports outside the repository.
- Enable operating-system full-disk encryption.
- Use an encrypted backup with a documented owner and retention period.
- Restrict directory permissions to the local account.
- Remove temporary uncompressed exports after checksum and backup verification.
- Never name local files with a person name, device serial, or health measurement.

If a raw file was ever pushed to GitHub, removing the working-tree file and
adding `.gitignore` is insufficient; Git history and any forks or artifacts
require a separate cleanup and exposure review.

## Secret management

Secrets include:

- Tidepool token or OAuth credentials.
- AWS credentials used during local collection.
- Pseudonymization HMAC keys.
- Any webhook or notification credentials.

Rules:

- Prefer short-lived AWS role credentials.
- Use AWS Secrets Manager or Databricks governed secrets for deployed workloads.
- Local `.env` is permitted only for development and must remain ignored.
- Do not print secret presence lengths, prefixes, or values.
- Do not embed secret values in Spark configuration, SQL text, object keys, or
  application resources.
- Assign a version identifier to the HMAC key without exposing the key.
- Test credential rotation before V1 release.

## Unity Catalog access model

| Identity | Bronze | Silver | Gold | Ops |
|---|---:|---:|---:|---:|
| Pipeline service principal | read/write | read/write | read/write | read/write |
| App service principal | none | none | select approved views/tables | select freshness only |
| Data owner | manage | manage | manage | manage |
| Demo app identity | no private catalog access | no private catalog access | demo catalog only | none |

- Grant permissions to groups or service principals, not broad workspace users.
- Bind private catalogs, external locations, and storage credentials to the
  private workspace when supported.
- Use governed tags for health-sensitive and identifier columns.
- Use column masks for role-specific query access when needed, but do not treat
  masks as sanitizing the underlying S3 files.
- Do not expose raw or masked private tables through Iceberg REST, path access,
  or external clients.

## Logging rules

Allowed log fields:

```text
batch_id
run_id
collector_version
contract_version
row_count
event-type counts
minimum and maximum event time
duration in seconds
status and non-sensitive error category
```

Disallowed log fields:

```text
token or credential value
device ID or serial number
source event ID or upload ID
glucose, insulin, carbohydrate, or pump-setting value
raw event or payload JSON
food name or annotation text
```

## Monitoring and alerts

| Signal | Suggested threshold | Response |
|---|---|---|
| Collector failures | Any consecutive failure after retry budget | Check auth/network; do not advance watermark. |
| Missing successful batch | More than 20 minutes for a 15-minute SLA | Run collector diagnostics and inspect Tidepool availability. |
| Manifest mismatch | Any checksum or row-count mismatch | Block ingestion for that batch. |
| Pipeline failure | Any failed update | Inspect pipeline event details; replay same update after correction. |
| Quarantine growth | Any new reason or sustained increase | Review source-contract or schema change. |
| Gold freshness | Older than 20 minutes | Check collector, Auto Loader, then Gold refresh in order. |
| Unauthorized access | Any denied event outside expected testing | Review IAM/UC audit logs and rotate credentials if necessary. |

Thresholds are initial operating values and should be adjusted after observing a
week of normal operation.

## Backup and retention

Document exact choices before release:

| Asset | Initial recommendation |
|---|---|
| Current raw S3 objects | Retain while TideTrack is in use. |
| Noncurrent S3 versions | 30–90 days, then delete. |
| Local uncompressed export | Delete after encrypted backup and S3 verification. |
| Encrypted local backup | One controlled copy with periodic restore test. |
| Bronze/Silver/Gold history | Retain according to analysis need; rebuildable from raw. |
| Operational logs | Short bounded retention with no health values. |

Do not enable permanent Object Lock until the owner has weighed ransomware
protection against the need to delete sensitive personal records.

## Recovery runbook requirements

### Collector failure

1. Confirm no manifest was published for an incomplete batch.
2. Identify the last successfully committed watermark.
3. Correct credentials or connectivity without changing source code contracts.
4. Re-run the same overlapping window.
5. Confirm Silver counts remain idempotent.

### Pipeline failure

1. Record pipeline update ID and exact failing dataset.
2. Check source manifest and contract version.
3. Inspect quarantine and rescued-data counts.
4. Correct pipeline code or source-contract mapping through normal review.
5. Deploy and run a selective refresh when appropriate.
6. Do not perform a full refresh without an explicit impact review.

### Suspected credential exposure

1. Disable or rotate the credential immediately.
2. Review CloudTrail, Unity Catalog, and application audit evidence.
3. Identify accessed objects and affected time range.
4. Replace the credential through the secret manager; do not edit it into code.
5. Document the event and preventive control change.

### Data deletion

1. Stop collectors and downstream refreshes.
2. Identify raw objects, noncurrent versions, UC tables, query results, local
   copies, backups, and derived artifacts in scope.
3. Follow the approved retention/deletion process for each system.
4. Verify removal and record non-sensitive evidence.

## Release security gate

- [ ] Repository scan finds no raw exports, tokens, serial numbers, or source IDs.
- [ ] Anonymous and unauthorized S3 tests fail.
- [ ] Collector cannot read or delete raw objects.
- [ ] App cannot access Bronze or Silver.
- [ ] Synthetic demo has no lineage to the private catalog.
- [ ] Logs contain only approved metadata.
- [ ] Credential rotation and one recovery scenario have been rehearsed.
- [ ] Retention and deletion decisions are documented.

## External references

- [AWS S3 security best practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)
- [AWS S3 Block Public Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [Databricks S3 external locations](https://docs.databricks.com/aws/en/connect/unity-catalog/cloud-storage/s3/)
- [Unity Catalog access control](https://docs.databricks.com/aws/en/data-governance/unity-catalog/access-control/)
- [Databricks secret management](https://docs.databricks.com/aws/en/security/secrets/)
