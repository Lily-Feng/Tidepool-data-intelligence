# Phase 2 plan — modeled gold, semantic layer, ML and the AI analyst

Phase 1 delivers bronze, current state, silver and the first daily gold tables.
Phase 2 turns that into a governed analytics product: a dimensional gold layer
built partly in PySpark, a semantic layer that Genie and the dashboard share,
descriptive ML on a feature table, a public diabetes knowledge base, and an AI
analyst app that answers questions from both — with governance and CI/CD written
as code throughout.

Related: [stage1-plan.md](stage1-plan.md) · [data-engineering-design.md](data-engineering-design.md)
· [data-contract.md](data-contract.md) · [dashboard-spec.md](dashboard-spec.md)

Status legend: ✅ built · 🟡 partial · ⬜ planned

---

## 1. Workstreams and order

| Step | Workstream | Deliverable | Gate |
|---|---|---|---|
| 2.1 | F. CI/CD and DataOps | PR checks, dev deploy on merge, golden data tests | A PR that breaks a metric fails CI |
| 2.2 | A. Dimensional gold (PySpark) | Conformed dimensions, `fct_glucose_5m`, `fct_daily`, `fct_meal`, `fct_overnight` | Basal allocation reconciles; golden metrics match |
| 2.3 | E. Governance as code | Grants, tags, masks, row filter, identifier and lineage checks | CI identity cannot read `personal` schemas |
| 2.4 | B. Semantic layer and Genie | Metric views, Genie space, benchmark set | Benchmark ≥ 90% correct on synthetic data |
| 2.5 | C. ML and feature engineering | `features_daily` feature table, three descriptive models, batch scoring, drift | Models registered, scored and reviewed |
| 2.6 | D1. Knowledge base | Licensed public sources → chunks → search index | Retrieval recall@5 ≥ 0.8 on the eval set |
| 2.7 | D2. AI analyst app | Agent over Genie + knowledge base, evaluation, app | 100% refusal on the adversarial set; care team finds the clinic report useful |

Prerequisite: Stage 1 build-order step 2 (first `dev` deploy with overlapping
synthetic windows). Build-order steps 4–5 (`features_5m`, `daily_summary`,
`meal_windows`, `overnight_windows`) are absorbed into 2.2 under dimensional names;
[data-engineering-design.md](data-engineering-design.md) section 8 is updated when
2.2 lands.

Phase 2's original items (Genie space, weekly AI summary, clinic report, N-of-1
experiment tracking) are delivered by 2.4 and 2.7.

---

## 2. Guardrails that shape every workstream

- **Descriptive and retrospective only.** No glucose forecasting, hypo
  prediction, dose or setting recommendation, or real-time output of any kind.
  Models run in batch over past days and describe them.
- **Dose amounts and setting values are never model features or levers.**
  Models may use settings *period* (a categorical version) but not basal rates,
  ratios or insulin totals as explanatory inputs, so no output can be read as
  "more insulin → better day".
- **Aggregates to language models.** LLM calls receive metric-view results and
  knowledge-base chunks, never per-reading traces or identifiers. Models are
  workspace-hosted (Foundation Model APIs).
- **Every AI answer** describes the data, cites the days or events behind it,
  cites knowledge-base sources by URL, and suggests discussing changes with the
  care team.
- **Only licensed public content** enters the knowledge base (section 7.1).

---

## 3. F. CI/CD and DataOps (2.1)

### 3.1 Pipelines

| Workflow | Trigger | Steps |
|---|---|---|
| `ci.yml` | Pull request | `ruff`; `pytest` (incl. local PySpark tests, Java on the runner); SQL lint (`sqlfluff`, Spark SQL dialect); privacy scan (the pre-commit patterns over the PR diff, plus `gitleaks`); `databricks bundle validate -t dev` |
| `deploy-dev.yml` | Merge to `main` | `bundle deploy -t dev`; generate synthetic batches with a fixed seed; run the pipeline; run data tests; run the Genie benchmark and agent evaluation (from 2.4 / 2.7); post a summary to the run |
| — | — | `personal` is **never** deployed from CI. The owner deploys it by hand after review. |

Authentication uses GitHub OIDC → Databricks workload identity federation for a
dedicated CI service principal. No personal access token is stored in GitHub.

Dev and `personal` share one workspace on Free Edition, so the CI principal is
granted only the user-prefixed `dev` schemas (enforced in 2.3, tested in CI).

### 3.2 Tests

| Layer | Test | Where |
|---|---|---|
| Unit | Pure PySpark transforms (bucket grid, basal overlap allocation, nearest reading, meal windows) on tiny hand-built frames | `tests/pipeline/`, local SparkSession |
| Golden | Synthetic seed → expected TIR, CV, GMI, basal and bolus totals per day, computed by an independent pandas reference in `tests/reference/` and compared with pipeline gold | `deploy-dev.yml` |
| Data | SQL assertions: every `dq_batch_reconciliation.rows_match`, basal allocation within 0.001 U, no fact row with an unknown dimension key, identifier check = 0 | `src/tests_sql/`, run as a job task |
| Semantic | Genie benchmark accuracy; agent evaluation scores | 2.4, 2.7 |

The synthetic generator gains `--subjects N` so dev data has several subjects;
this exercises the row filter (2.3) and joins on `subject_key`.

---

## 4. A. Dimensional gold, built in PySpark (2.2)

### 4.1 Model

Gold becomes a star schema in `private_analytics`. The four analysis shapes from
the design doc map onto it: timeline → `fct_glucose_5m`, daily → `fct_daily`,
event windows → `fct_meal` / `fct_overnight`, periods → `dim_settings_version`.

**Conformed dimensions**

| Dimension | Grain | Type | Notes |
|---|---|---|---|
| `dim_subject` | One pseudonymous subject | SCD1 | `subject_key` only for now; ready for more subjects |
| `dim_date` | One local calendar day | Static, generated | `weekday`, `is_weekend`, `iso_week`, `month`, `is_dst_change_day` |
| `dim_time_of_day` | One 5-minute slot (288 rows) | Static | `slot`, `hour`, `day_part` (overnight / morning / afternoon / evening) |
| `dim_settings_version` | One settings version | SCD2 | From `settings_history`: `settings_key`, `valid_from_utc`, `valid_to_utc`, `is_current`, segment counts. Values stay in silver |
| `dim_site` | One infusion site | SCD1 | From `site_changes`: `site_key`, start, end, `site_hours` |

**Facts**

| Fact | Grain | Kind | Measures | Keys |
|---|---|---|---|---|
| `fct_glucose_5m` | Subject × 5-minute bucket, all 288 per day | Periodic snapshot, dense | `glucose_mg_dl`, `cgm_present`, `basal_units`, `bolus_units`, `carbs_g`, `override_active` | subject, date, time of day, settings, site |
| `fct_daily` | Subject × local day | Periodic snapshot | Readings, coverage, TIR/TBR/TAR counts, sum and sum of squares of glucose, insulin, carbs, `valid_day` | subject, date, settings, site day |
| `fct_meal` | One carb entry | Transaction (window) | Start, peak, rise, minutes to peak, 2 h / 3 h glucose, pre-bolus minutes, `overlapping_meal`, coverage | subject, date, time of day, settings, site |
| `fct_overnight` | One night 00:00–06:00 | Periodic snapshot | TIR, min, lows count, CV, bedtime glucose, late carbs | subject, date, settings, site |

Facts store **additive components** (counts, sums, sums of squares), not only
percentages, so the semantic layer can compute TIR or CV correctly over any
period instead of averaging daily percentages.

`daily_glucose` and `daily_insulin_carbs` become thin views over `fct_daily`
for the dashboard, then retire.

### 4.2 PySpark components

Python pipeline files (`pyspark.pipelines`) call pure functions in
`src/pipeline/lib/`, so the same code runs in the pipeline and in unit tests.

| Function | Technique |
|---|---|
| `bucket_grid(days, subjects)` | `sequence` + `explode` over a calendar, so empty buckets exist |
| `allocate_basal(intervals, grid)` | Range join on interval overlap; units = rate × overlap seconds / 3600 |
| `nearest_reading(cbg, grid)` | Window ranking by distance to bucket start within the bucket |
| `meal_windows(carbs, grid)` | Range join −30 to +240 min; peak and time-to-peak via window aggregates |
| `overnight(grid)` | Group by local night; flags coverage < 70% |

Dimensions stay in SQL; the dense timeline and window facts are PySpark.

### 4.3 Checks

- `private_ops.dq_basal_allocation`: per day, bucket basal sum vs interval
  `delivered_units`, tolerance 0.001 U.
- Expectations on facts: dimension keys not null; 288 buckets per subject-day.

---

## 5. E. Governance as code (2.3)

| Control | Implementation |
|---|---|
| Grants | `grants:` on each schema in `resources/storage.yml`, per target. Owner group: all; CI principal: `dev` schemas only; app principal: `private_analytics` and `public_reference` read only |
| Run identity | Jobs and the pipeline `run_as` a service principal in `personal` |
| Tags | Governed tags `sensitivity` = `restricted` / `pseudonymized` / `aggregate` / `public`, and `contains_identifiers`, applied idempotently by a `governance` job task (`src/governance/tags.sql`) after each pipeline update |
| Column mask | `event_json` and `source_file` in `private_raw` masked for anyone outside the owner group |
| Row filter | Curated and analytics tables filtered by `subject_key` through `private_ops.subject_access` (principal → subject). One subject today; the mechanism is ready for more |
| Identifier check | `private_ops.gov_identifier_check`: columns tagged `contains_identifiers` outside `private_raw` must be 0 (also a CI data test) |
| Lineage | Saved queries over `system.access.table_lineage` / `column_lineage` showing raw → silver → gold → metric view, and over `system.access.audit` for reads of `private_raw` |
| Docs | `docs/governance.md`: schema × principal × privilege matrix and tag dictionary |

---

## 6. B. Semantic layer and Genie (2.4)

### 6.1 Metric views

YAML metric views in `src/semantic/metric_views/`, deployed to
`private_analytics`. Each defines the measure once, with its unit and consensus
target in the comment.

| Metric view | Source | Measures | Dimensions |
|---|---|---|---|
| `glucose_metrics` | `fct_glucose_5m` + dims | readings, coverage %, mean, TIR / TBR <70 / <54 / TAR >180 / >250 %, CV % (from sums), GMI % | date, week, weekday, day part, hour, site day, settings version |
| `daily_metrics` | `fct_daily` + dims | valid days, basal / bolus / total units per day, carbs per day | date, week, weekday, settings version, site day |
| `meal_metrics` | `fct_meal` + dims | meals, median rise, median minutes to peak, % meals with 2 h glucose in range | day part, pre-bolus bucket, weekday, settings version |
| `overnight_metrics` | `fct_overnight` + dims | nights, overnight TIR, nights with a low | weekday, late-carbs flag, settings version |

The dashboard reads the same metric views, so dashboard and Genie can't
disagree.

### 6.2 Genie space

Defined in `src/semantic/genie/` and exported via the Genie API (or a bundle
resource if available) so it is reviewable in git.

- **Data:** the four metric views and the conformed dimensions only. No silver,
  no `private_raw`.
- **Instructions:** consensus definitions; local days; always state days and
  coverage; minimum 14 valid days for a comparison; describe, never recommend;
  refuse dosing or setting questions with the standard care-team sentence.
- **Example SQL:** 15–20 trusted queries (TIR by weekday, meal rise by pre-bolus
  bucket, before/after a settings version, overnight TIR with late carbs).
- **Benchmarks:** `benchmarks.yaml`, 30 questions with expected answers on the
  seeded synthetic data, run in `deploy-dev.yml`. Target ≥ 90%.

---

## 7. D. Knowledge base and AI analyst (2.6, 2.7)

### 7.1 Source policy

`src/knowledge/sources.yaml` is an allowlist; nothing is crawled beyond it.
Each entry records URL, publisher, license, and retrieval date.

| Allowed | Examples | Rule |
|---|---|---|
| U.S. federal public-domain health content | NIDDK, CDC diabetes pages, MedlinePlus | Ingest; cite |
| Openly licensed articles | PubMed Central open-access subset, CC BY / CC0 only | Ingest; keep license per document |
| Copyrighted guidelines and center websites | Professional-society standards of care, hospital and diabetes-center pages | Cite by link only, unless the terms explicitly permit reuse |

The fetcher respects `robots.txt` and rate limits. Documents live in the
workspace, not in the repo; the repo holds only the allowlist and code.

### 7.2 Knowledge pipeline

```text
sources.yaml ─▶ fetch job ─▶ /Volumes/<catalog>/public_reference/kb_raw/<doc_id>/   (immutable)
                                  │  ai_parse_document
                                  ▼
                 public_reference.kb_documents   one row per document (url, license, title, dates)
                 public_reference.kb_chunks      one row per section chunk (~500 tokens, overlap)
                                  │  embeddings (workspace-hosted model)
                                  ▼
                 Vector Search delta-sync index on kb_chunks
                 (fallback for a small corpus: embedding column + cosine similarity in SQL)
```

`public_reference` holds no personal data and is tagged `sensitivity=public`.
Retrieval eval: 40 questions → expected document; target recall@5 ≥ 0.8.

### 7.3 AI analyst

An agent with read-only tools and no write path anywhere:

| Tool | Backed by | Returns |
|---|---|---|
| `ask_my_data` | Genie Conversation API on the 2.4 space | Aggregated results + the SQL used + day counts |
| `search_knowledge` | `kb_chunks` index | Chunks with URL and license |
| `period_compare` | UC SQL function over metric views | Baseline vs intervention period (N-of-1) |

**Answer contract:** what the data shows (numbers, days, coverage) → relevant
general background from cited sources → "discuss any change with your care
team". General background never tells the user what to change.

**Guardrail layers:** (1) an input classifier for dosing, setting, real-time or
emergency intent, which returns a fixed refusal with the care-team sentence
(and the emergency-services sentence for urgent symptoms); (2) system prompt;
(3) an output check before return that blocks dose numbers or imperative setting
advice.

**Evaluation** (MLflow GenAI, run in `deploy-dev.yml`):

| Set | Size | Scorers | Target |
|---|---|---|---|
| Data questions on synthetic data | 30 | Correctness vs expected | ≥ 85% |
| Knowledge questions | 20 | Retrieval groundedness; sources cited | ≥ 90% |
| Adversarial (dose, settings, "should I", urgent symptoms) | 20 | Guidelines: refuses, no dose numbers, care-team sentence | 100% |

Traces go to a private MLflow experiment.

**Surfaces:** a Databricks App (chat + clinic report page) deployed by the
bundle; the weekly summary as a scheduled job writing to
`private_analytics.weekly_summaries`. The `dev` app runs on synthetic data and
is the only one shown publicly.

---

## 8. C. ML and feature engineering (2.5)

### 8.1 Feature table

`private_analytics.features_daily`: primary key `(subject_key, local_date)`,
timeseries key `local_date`, registered as a Unity Catalog feature table.
Context features only: weekday, site day, override minutes, alarm count, late
carbs, median pre-bolus minutes, meals count, settings version (categorical),
previous-day TIR; later sleep minutes, HRV, steps, workout minutes. Labels
(daily TIR, overnight lows) are joined at training time with point-in-time
lookups, never stored as features.

### 8.2 Models

| Model | Method | Output table | Question it describes |
|---|---|---|---|
| Day patterns | K-means / Gaussian mixture on each day's 24 hourly glucose medians | `day_patterns` (date → pattern, distance) | "What kinds of days do I have, and how often?" |
| TIR associations | Gradient boosting + SHAP, with a regularized linear baseline; blocked time-series cross-validation | `tir_associations` (feature, direction, effect size, n days, CV score) | "Which context factors go with higher or lower TIR days?" |
| Unusual nights | Isolation forest on `fct_overnight` | `unusual_nights` (night → score, contributing features) | "Which past nights are worth reviewing?" |

Outputs are associations over the owner's own history, reported next to the
stratified comparisons (design doc section 10) and subject to the same evidence
rules (≥ 14 valid days, n shown, confounding checked).

### 8.3 MLOps

- Training job weekly; MLflow experiment per model; models registered in
  `private_ml` with `@champion` / `@challenger` aliases; a challenger is
  promoted only if its CV score is no worse and the owner approves.
- Batch scoring with the feature-store client, so scoring reads the same
  features training did.
- `private_ops.ml_feature_drift`: population stability index per feature, last
  30 days vs training window. Counts and scores only.
- Model cards in `docs/models/` (generic: purpose, features, limits; no
  personal results).

---

## 9. Repo layout additions

```text
.github/workflows/ci.yml, deploy-dev.yml
resources/          + grants, run_as, ml.yml, knowledge.yml, app.yml
src/pipeline/lib/   PySpark transform functions (unit-tested)
src/pipeline/transformations/gold/   dim_*.sql, fct_*.py
src/governance/     tags.sql, masks.sql, row_filters.sql
src/semantic/       metric_views/*.yaml, genie/ (instructions, examples, benchmarks)
src/ml/             features.py, train_*.py, score.py
src/knowledge/      sources.yaml, fetch.py, pipeline SQL
src/agent/          agent, tools, guardrails, eval datasets (synthetic only)
src/app/            Databricks App
src/tests_sql/      data assertions
tests/pipeline/, tests/reference/
docs/governance.md, docs/models/
```

New schemas: `private_ml` (models, inference outputs) and `public_reference`
(knowledge base).

---

## 10. Open questions (check on Free Edition first)

| Feature | Fallback if unavailable |
|---|---|
| Service principals, groups, workload identity federation | Run as owner; CI limited to `bundle validate` with a scoped token in a separate dev workspace |
| System tables (lineage, audit) | Lineage screenshots from Catalog Explorer; identifier check still runs on `information_schema` |
| Governed tags, row filters, column masks | Dynamic views in a separate schema |
| Metric views | Gold views with documented measure SQL; Genie instructions carry the definitions |
| Genie API / bundle resource | Document the space by hand in `src/semantic/genie/` |
| Vector Search | Embedding column + SQL cosine similarity (corpus is small) |
| `ai_parse_document` | Parse HTML/PDF in Python in the fetch job |
| Databricks Apps | Notebook-based agent UI; app deferred |
| Feature engineering client on serverless | Plain Delta feature table with explicit point-in-time joins |
