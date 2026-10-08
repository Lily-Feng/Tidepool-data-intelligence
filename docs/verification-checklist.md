# Manual verification checklist

Run each step by hand, in order, and tick it off. Goal: confirm the schemas,
volume, pipeline, tables and job exist and are ready to receive new data.

Use only **synthetic** data for the `dev` target. Do not paste real output
into public files.

Placeholders: `<profile>` = your CLI profile, `<catalog>` = `twiistlab`
(bundle variable), `<user>` = your username prefix.

> In `dev` mode the bundle prefixes resource names (e.g. `dev_<user>_private_raw`
> and a `[dev <user>]` pipeline/job name). Run `databricks schemas list <catalog>`
> in step 3 to see the real names and substitute them in later steps.
> `personal` (production mode) uses the plain names.

---

## A. Local prerequisites

- [ ] A1. CLI installed: `databricks --version`
- [ ] A2. Logged in: `databricks auth login --profile <profile>`, then
      `databricks current-user me --profile <profile>` returns your user.
- [ ] A3. Tests pass locally: `python -m pytest tests`
- [ ] A4. Pre-commit hook installed: `git config core.hooksPath scripts/git-hooks`

## B. Workspace prerequisites

- [ ] B1. Catalog exists: `databricks catalogs get <catalog> --profile <profile>`
      (the bundle does **not** create the catalog; create it in the UI or with
      `databricks catalogs create <catalog>` if missing).
- [ ] B2. You have `USE CATALOG` and `CREATE SCHEMA` on it (Catalog Explorer ->
      catalog -> Permissions).
- [ ] B3. Serverless compute is available (run a trivial query in the SQL editor
      or a serverless notebook). If not, see "Troubleshooting".
- [ ] B4. A SQL warehouse exists and is running (needed for the SQL checks below).
      `databricks warehouses list --profile <profile>`

## C. Validate and deploy the bundle

- [ ] C1. `databricks bundle validate -t dev --profile <profile>` prints
      "Validation OK".
- [ ] C2. `databricks bundle deploy -t dev --profile <profile>` completes with no errors.
- [ ] C3. `databricks bundle summary -t dev --profile <profile>` lists the 4 schemas,
      the volume, the pipeline and the job, with URLs.

## D. Verify infrastructure (before any data)

Run in the SQL editor or with the CLI. Replace schema names if prefixed.

- [ ] D1. Schemas: `SHOW SCHEMAS IN <catalog>;`
      Expect `private_raw`, `private_curated`, `private_analytics`, `private_ops`.
- [ ] D2. Volume: `SHOW VOLUMES IN <catalog>.private_raw;` -> `landing`.
- [ ] D3. Volume is writable and empty:
      `databricks fs ls dbfs:/Volumes/<catalog>/private_raw/landing --profile <profile>`
- [ ] D4. Pipeline exists: `databricks pipelines list-pipelines --profile <profile>`
      (or Jobs & Pipelines in the UI). Open it and confirm: serverless, catalog
      `<catalog>`, default schema `private_curated`, root `src/pipeline`.
- [ ] D5. Pipeline source files were picked up: in the pipeline UI, open the
      graph/"Settings -> Source code" and confirm all 17 SQL files under
      `transformations/` are listed (bronze 3, silver 9, gold 2, ops 3).
- [ ] D6. Pipeline configuration values are set: `catalog`, `raw_schema`,
      `analytics_schema`, `ops_schema`, `landing_root`, `subject_key`,
      `spark.sql.session.timeZone = UTC`.
- [ ] D7. Job exists: `databricks jobs list --profile <profile>` shows `twiistlab-refresh`.
      Open it: one task `refresh` (pipeline task) and a file-arrival trigger on
      the volume path.
- [ ] D8. Trigger state: UNPAUSED in `personal`; **PAUSED** in `dev` (expected).
      Leave paused while testing by hand.

## E. Dry run on an empty volume (optional but useful)

- [ ] E1. Run the pipeline: `databricks bundle run tidepool -t dev --profile <profile>`
- [ ] E2. Update completes (or fails with a clear "no files" message). Note the result.
- [ ] E3. Tables exist even if empty, check: `SHOW TABLES IN <catalog>.private_raw;`
      Expect `tidepool_events_raw`, `tidepool_events_current`.
      `SHOW TABLES IN <catalog>.private_ops;` -> `ingest_manifests`, `dq_*`.

## F. Load a synthetic batch

- [ ] F1. Generate synthetic export (no real data):
      `python src/synthetic/generate_tidepool.py --days 14 --out <scratchpad>/synthetic.json`
- [ ] F2. Package only (dry run), inspect the batch folder:
      `python src/ingest/tidepool_export.py <scratchpad>/synthetic.json`
      Confirm `events.ndjson.gz` and `manifest.json` are written; check the
      printed counts.
- [ ] F3. Upload:
      `python src/ingest/tidepool_export.py <scratchpad>/synthetic.json --upload --volume /Volumes/<catalog>/private_raw/landing --profile <profile>`
- [ ] F4. Confirm files landed:
      `databricks fs ls dbfs:/Volumes/<catalog>/private_raw/landing/tidepool_export --profile <profile>`
      (one folder per batch, containing both files).

## G. Run the pipeline and verify tables

- [ ] G1. `databricks bundle run tidepool -t dev --profile <profile>` ends in COMPLETED.
- [ ] G2. Pipeline UI shows every dataset green, with row counts > 0 (except
      datasets that legitimately have no synthetic rows).
- [ ] G3. Bronze:
      ```sql
      SELECT COUNT(*) FROM <catalog>.private_raw.tidepool_events_raw;
      SELECT COUNT(*) FROM <catalog>.private_raw.tidepool_events_current;
      ```
      `current` count <= `raw` count (deduplicated by event id).
- [ ] G4. Silver tables exist in `private_curated` and have rows:
      `cbg_events`, `smbg_events`, `bolus_events`, `basal_intervals`,
      `carb_events`, `pump_events`, `settings_history`, `site_changes`.
      `SHOW TABLES IN <catalog>.private_curated;`
- [ ] G5. Silver has no direct identifiers: `DESCRIBE <catalog>.private_curated.cbg_events;`
      Columns should contain the pseudonymous subject key, not user or device IDs.
- [ ] G6. Gold: `SELECT * FROM <catalog>.private_analytics.daily_glucose LIMIT 10;`
      and `daily_insulin_carbs`. Spot-check: one row per day, values plausible.
- [ ] G7. Ops: `SELECT * FROM <catalog>.private_ops.ingest_manifests;` shows 1 row
      for the batch; `dq_batch_reconciliation` shows manifest count = loaded
      count (no mismatch); `dq_event_conflicts` is empty; `dq_freshness` shows
      the latest event time.

## H. Verify incremental loading (new data arrives)

- [ ] H1. Generate two overlapping slices:
      `python src/synthetic/generate_tidepool.py --days 14 --window 0:9 --out <scratchpad>/a.json`
      `python src/synthetic/generate_tidepool.py --days 14 --window 6:14 --out <scratchpad>/b.json`
- [ ] H2. Upload `a.json`, run pipeline, note counts of `tidepool_events_current`.
- [ ] H3. Upload `b.json`, run pipeline. Expect `current` to grow only by the
      non-overlapping events, `raw` to grow by all of `b`, and
      `ingest_manifests` to show 2 batches.
- [ ] H4. Re-upload the same file: the packager should detect the duplicate
      (same `source_sha256`) and not create a second batch.
- [ ] H5. Check `dq_event_conflicts` is still empty after overlap.

## I. Verify automatic trigger

- [ ] I1. In the job UI, unpause the trigger (dev only).
- [ ] I2. Upload a new synthetic batch (step F3).
- [ ] I3. Within about 5 minutes (`wait_after_last_change_seconds: 300`), a
      job run starts by itself. Check Job runs -> trigger type "File arrival".
- [ ] I4. Run succeeds and the new batch appears in `ingest_manifests`.
- [ ] I5. Pause the trigger again when done.

## J. Cleanup and next step

- [ ] J1. `databricks bundle destroy -t dev --profile <profile>` removes the dev
      resources (it deletes the volume and its files; only do this for synthetic data).
- [ ] J2. Repeat sections C-G with `-t personal` and your real export, only after
      `dev` is fully green. Real data stays in `private/`.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `RESOURCE_EXHAUSTED` creating a cluster | Serverless not available or quota exhausted. Check B3, terminate idle clusters (`databricks clusters list`), retry later, or switch the pipeline to a small classic cluster. |
| `bundle validate` fails on catalog | Catalog missing or no permission (B1, B2). |
| Pipeline update fails with path errors | `landing_root` config wrong, or the dev schema prefix not reflected; compare with `SHOW SCHEMAS`. |
| Tables empty after run | Batch folder not under `landing/tidepool_export/`, or files not `.ndjson.gz`. Re-check F4. |
| Trigger never fires | Still paused (dev), or the volume path in the trigger differs from the upload path. |
