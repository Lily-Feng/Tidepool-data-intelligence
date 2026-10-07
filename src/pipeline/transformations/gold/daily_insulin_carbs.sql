-- Gold: daily insulin and carb totals by local calendar day.
CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.${analytics_schema}.daily_insulin_carbs
COMMENT 'Daily basal, bolus and carb totals by local day.'
AS WITH days AS (
  SELECT subject_key, local_date,
         sum(delivered_units) AS basal_units, 0D AS bolus_units, 0D AS carbs_g
  FROM basal_intervals GROUP BY ALL
  UNION ALL
  SELECT subject_key, local_date, 0D, sum(delivered_units), 0D
  FROM bolus_events GROUP BY ALL
  UNION ALL
  SELECT subject_key, local_date, 0D, 0D, sum(carbs_g)
  FROM carb_events GROUP BY ALL
)
SELECT
  subject_key,
  local_date,
  round(sum(basal_units), 2) AS basal_units,
  round(sum(bolus_units), 2) AS bolus_units,
  round(sum(basal_units) + sum(bolus_units), 2) AS total_units,
  round(sum(carbs_g), 0) AS carbs_g
FROM days
GROUP BY subject_key, local_date;
