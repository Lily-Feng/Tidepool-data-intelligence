# Dashboard specification

Stage 1 surface: a Databricks **AI/BI dashboard** over the curated gold tables,
followed by a **Genie space** in Phase 2. A custom Databricks App is deferred
until these fall short.

The dashboard is informational analytics. It must not recommend dosing,
predict a medical outcome, or imply that a displayed range is clinical advice.

## User questions

1. Is the data current and complete for the selected period?
2. What was the glucose trajectory, and how much time was in range?
3. How much basal and bolus insulin was recorded, and how many carbs?
4. When did insulin and carbohydrate events occur relative to glucose changes?
5. Are there missing or dropped records that limit interpretation?

## Pages

| Page | Contents | Source |
|---|---|---|
| Overview | KPI counters (mean glucose, TIR, TBR <70, CV, GMI, CGM coverage); daily TIR/TBR/TAR stacked bar; daily mean glucose line; daily basal/bolus bar + carbs | `daily_glucose`, `daily_insulin_carbs` |
| Timeline | 5-minute glucose line with insulin and carbs aligned below (not a dual axis) | `cbg_events`, `basal_intervals`, `bolus_events`, `carb_events` |
| Data quality | Last batch and pipeline update, coverage by day, rows dropped by expectations | gold tables + pipeline event log |

Global filter: date range (default last 14 days). All metrics use local
calendar days.

## Metric definitions

Consensus CGM targets: TIR 70–180 mg/dL > 70%, TBR < 70 mg/dL < 4%,
TBR < 54 mg/dL < 1%, CV ≤ 36%. GMI = 3.31 + 0.02392 × mean mg/dL.
Coverage = readings / 288 per day. Show unit, period and coverage next to every
KPI. Reference lines for targets are labeled as consensus targets, not as advice.

## Rules

- Time runs left to right; bars start at zero; missing CGM intervals are gaps,
  never interpolated.
- Partial current day is labeled partial.
- No event keys, device or upload IDs, or free text on any widget.
- Footer on every page: "Informational personal analytics; not medical advice
  or a dosing recommendation."
- Screenshots of the real dashboard stay in `private/`. Public screenshots use
  the `dev` target with synthetic data.
