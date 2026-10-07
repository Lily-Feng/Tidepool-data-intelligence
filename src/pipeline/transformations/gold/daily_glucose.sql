-- Gold: descriptive daily CGM metrics. Local calendar days; consensus ranges.
-- Patterns only; nothing here recommends a dose or setting.
CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.${analytics_schema}.daily_glucose
COMMENT 'Daily CGM metrics: TIR 70-180, TBR <70/<54, TAR >180/>250, CV, GMI, coverage.'
AS SELECT
  subject_key,
  local_date,
  count(*) AS readings,
  round(100 * count(*) / 288.0, 1) AS cgm_coverage_pct,
  round(avg(glucose_mg_dl), 1) AS mean_mg_dl,
  round(100 * avg(CASE WHEN glucose_mg_dl BETWEEN 70 AND 180 THEN 1 ELSE 0 END), 1) AS tir_pct,
  round(100 * avg(CASE WHEN glucose_mg_dl < 70 THEN 1 ELSE 0 END), 1) AS tbr_70_pct,
  round(100 * avg(CASE WHEN glucose_mg_dl < 54 THEN 1 ELSE 0 END), 1) AS tbr_54_pct,
  round(100 * avg(CASE WHEN glucose_mg_dl > 180 THEN 1 ELSE 0 END), 1) AS tar_180_pct,
  round(100 * avg(CASE WHEN glucose_mg_dl > 250 THEN 1 ELSE 0 END), 1) AS tar_250_pct,
  round(100 * stddev(glucose_mg_dl) / avg(glucose_mg_dl), 1) AS cv_pct,
  round(3.31 + 0.02392 * avg(glucose_mg_dl), 2) AS gmi_pct
FROM cbg_events
GROUP BY subject_key, local_date;
