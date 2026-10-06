# TideTrack Studio V1 dashboard/App specification

## Direction

The V1 app is a read-only analytic dashboard for one authorized person who
wants to understand glucose history, insulin delivery, data completeness, and
the timing relationships between events over a selected period.

- Genre: analytic dashboard.
- Primary task: move from period overview to a detailed five-minute timeline.
- Device target: desktop first, usable on tablet, readable rather than fully
  featured on mobile.
- Refresh objective: source collection every five minutes and app-visible data
  within 15 minutes under normal operation.
- Execution identity: application service principal with `SELECT` on approved
  Gold tables only.

The app is informational analytics. It must not recommend dosing, predict a
medical outcome, or imply that a displayed range is clinical advice.

## V1 user questions

1. Is the data current and complete for the selected period?
2. What was the glucose trajectory?
3. How much basal and bolus insulin was recorded?
4. When did insulin and carbohydrate events occur relative to glucose changes?
5. Are there missing or quarantined records that limit interpretation?

## Navigation and composition

Use one application page with three `Tabs`:

1. **Overview** — headline KPIs and daily trends.
2. **Timeline** — five-minute glucose and insulin detail.
3. **Data quality** — freshness, coverage, and exceptions.

Use a stratified layout:

```text
Title + source/freshness + informational disclaimer
Date-range selector + refresh status
KPI cards
Primary trend chart
Supporting insulin/carbohydrate chart
Detail or quality table
Definitions/source footer
```

The critical freshness status remains visible across all tabs. Detailed raw
records are not exposed from the dashboard.

## Global controls

- Date-range `Select`: last 24 hours, 7 days, 14 days, and 30 days.
- Optional local/UTC display toggle only if timestamp confusion appears in user testing.
- Refresh action reruns app queries; it does not trigger source ingestion in V1.
- Source/freshness `Badge` shows the maximum `feature_as_of_utc` and pipeline status.

All SQL parameters use AppKit query parameters. Never concatenate user input
into SQL.

## Overview tab

### KPI row

AppKit has no prebuilt KPI component. Compose each metric from `Card`,
`CardHeader`, `CardTitle`, and `CardContent`, using `useAnalyticsQuery`.

| KPI | Definition | Required context |
|---|---|---|
| Latest glucose | Most recent valid CBG value | Unit, event time, data age, source |
| Mean glucose | Arithmetic mean over selected valid CBG records | Unit, selected period, coverage |
| Target-range share | Share within owner-configured range | Range definition, selected period, missingness |
| Basal delivered | Sum of interval-overlap basal units | Units, selected period |
| Bolus delivered | Sum of delivered bolus units | Units, selected period |
| Data coverage | Valid five-minute CBG buckets / expected buckets | Percent, expected/observed counts |

Do not color latest glucose or target-range share as good/bad by default. If
threshold colors are introduced later, the owner-configured thresholds and
semantic meaning must be visible.

### Daily trend

- Component: `LineChart` bound to `daily_metrics` query.
- Primary series: daily mean glucose using the primary/foreground semantic series.
- Comparison: optional configured range shown as reference lines only after
  confirming current chart support in the installed AppKit documentation.
- Time runs left to right with consistent units.
- Partial current day is marked and explained rather than compared as a full day.

### Daily insulin structure

- Component: `BarChart` bound to `daily_insulin` query.
- Series: basal and bolus units using a categorical palette.
- Use a zero baseline and consistent scale across the selected period.
- Title identifies subject, measure, unit, and selected dates.

## Timeline tab

### Glucose timeline

- Component: `LineChart` bound to `glucose_timeline`.
- X-axis: local display time derived from UTC plus per-event offset.
- Y-axis: source glucose unit.
- Missing intervals appear as gaps, not interpolated continuous lines.
- Tooltip includes event time, value, unit, data quality, and data age.

### Insulin timeline

- Component: `BarChart` or `AreaChart`, after confirming the installed AppKit
  component API.
- Basal shows units allocated to each five-minute bucket.
- Bolus shows discrete units in the event bucket.
- Glucose and insulin charts are vertically aligned by time rather than placed
  on a misleading dual axis.

### Event table

- Component: `DataTable` with server-side date filtering and pagination.
- Columns: local time, event category, normalized value, unit, and quality status.
- Exclude raw IDs, device IDs, upload IDs, payload JSON, and annotations.

## Data-quality tab

### Summary cards

- Latest successful collector batch.
- Latest successful pipeline update.
- Gold freshness age.
- Missing expected CBG buckets.
- Quarantine count by selected period.

### Quality table

- Component: `DataTable` bound to `data_quality_summary`.
- Columns: date, issue category, affected row count, first occurrence, last occurrence.
- Show issue categories, not raw sensitive records.

## SQL query contract

Create these files before UI implementation:

```text
config/queries/dashboard_kpis.sql
config/queries/daily_metrics.sql
config/queries/daily_insulin.sql
config/queries/glucose_timeline.sql
config/queries/insulin_timeline.sql
config/queries/event_summary.sql
config/queries/data_quality_summary.sql
config/queries/data_freshness.sql
```

Each query:

- Reads only approved `tidetrack_private.gold` or safe `ops` views.
- Requires bounded start/end parameters where applicable.
- Returns aggregated or paginated data, not an unrestricted raw dump.
- Provides explicit aliases and stable column types for AppKit type generation.
- Includes source/freshness fields where a component displays a metric.
- Remains below the 1 MB analytics event payload limit.

After SQL is defined, run AppKit type generation and use the generated types
before writing `App.tsx`.

## Component plan

| Element | AppKit primitive | Data binding | Required states |
|---|---|---|---|
| Page navigation | `Tabs` | Client state | Active tab visible |
| Period selector | `Select` | Typed SQL parameters | Disabled while required query state changes |
| Freshness status | `Badge` | `data_freshness` query | Current, stale, partial |
| KPI | Composed `Card` primitives | `useAnalyticsQuery` | `Skeleton`, `Empty`, inline error |
| Daily trend | `LineChart` | `daily_metrics` query key | Loading, empty, error, partial day |
| Daily insulin | `BarChart` | `daily_insulin` query key | Loading, empty, error |
| Glucose timeline | `LineChart` | `glucose_timeline` query key | Missing gaps, stale note |
| Insulin timeline | `BarChart`/confirmed chart | `insulin_timeline` query key | Empty and partial intervals |
| Event summary | `DataTable` | `event_summary` query key | Pagination, empty, error |
| Quality summary | `DataTable` | `data_quality_summary` query key | Pagination, empty, error |
| No-data guidance | `Empty` | Query state | Explain date-range or ingestion action |
| Failure message | `Alert` | Query error | Actionable retry/support text |
| Loading placeholder | `Skeleton` | Query loading state | Preserve layout dimensions |

Exact component props must be confirmed using the AppKit documentation shipped
with the installed package. Do not guess API signatures or hardcode chart colors.

## Notation and color

- Titles identify measure, unit, and period; use a data-derived finding only
  when it can be stated accurately.
- Use a common scale for charts intended for comparison.
- Time always runs left to right.
- Bars start at zero.
- Use semantic tokens or chart palettes; never raw hex or raw Tailwind colors.
- Use color for series identity, freshness warning, or quality status—not decoration.
- Always pair status color with text or an icon for accessibility.
- Clearly mark partial current periods and missing data.

## Required states

Every query-backed region implements:

- Loading: `Skeleton` with stable dimensions.
- Empty: `Empty` explaining whether to change the date range or check ingestion.
- Error: inline `Alert` with retry guidance.
- Stale: retain the last available result with a freshness warning.
- Partial: display available data and state what is missing.

The application must never present a blank chart as if it represented zero.

## Accessibility and privacy

- Keyboard-reachable tabs and controls.
- Visible focus treatment.
- Text alternatives for status color.
- Units included in labels and tooltips.
- No device ID, upload ID, source event ID, serial number, or raw annotation in
  HTML, browser logs, query payloads, URLs, or telemetry.
- Persistent footer: `Informational personal analytics; not medical advice or a dosing recommendation.`

## Performance objectives

- Typical dashboard query completion: under five seconds on a warm warehouse.
- Visible loading state immediately.
- No app request longer than the platform proxy timeout.
- Timeline queries bounded by the selected period.
- Tables use server-side pagination, sorting, and filtering.
- Default period is seven days; 30-day detail may use coarser aggregation if
  required to remain under payload limits.

## V1 acceptance tests

- [ ] Overview renders with a complete seven-day synthetic fixture.
- [ ] A date range with no data shows an actionable empty state.
- [ ] A query failure shows an inline error without breaking other panels.
- [ ] Stale data remains visible with a clear freshness warning.
- [ ] Missing CGM intervals render as gaps.
- [ ] Partial current-day metrics are labeled partial.
- [ ] Changing the date-range preset updates every dependent query.
- [ ] No browser or app log contains restricted source identifiers or values.
- [ ] Smoke tests use actual TideTrack headings/selectors, not template defaults.
- [ ] The app service principal cannot query Bronze or Silver.
- [ ] The informational-use disclaimer is visible on every tab.

## Explicitly excluded from V1

- Genie/chat and generated SQL.
- Predictions or model-serving calls.
- Alerts presented as medical recommendations.
- Forms, annotations, and saved user state.
- Raw event export from the application.
- Multi-user row-level security.

