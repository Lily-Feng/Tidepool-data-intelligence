# Scripts

This folder contains starter scripts for TideTrack Studio.

## `ingest_tidepool.py`

Use this script as a template for secure Tidepool ingestion.

### Security guidelines

- Store your Tidepool token in `TIDEPOOL_API_TOKEN`.
- Do not commit API keys or medical data to GitHub.
- If you use GitHub Actions later, store the token in repository secrets.

### V1 implementation context

The current script is a placeholder, not a production collector. Implement it
against the contracts in:

- [`docs/v1/data-contract.md`](../docs/v1/data-contract.md)
- [`docs/v1/workstreams.md`](../docs/v1/workstreams.md)
- [`docs/v1/security-operations.md`](../docs/v1/security-operations.md)

The V1 collector should first support a protected export backfill, then an
authorized incremental API path. It writes immutable compressed NDJSON batches
and manifests to private S3; it does not write directly to DBFS or Delta tables.
