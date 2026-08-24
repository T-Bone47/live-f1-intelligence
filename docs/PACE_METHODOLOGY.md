# PACE_METHODOLOGY.md

Normative methodology for pace metrics (Phase 2). All outputs DERIVED.

## 1. Eligibility

A lap enters pace samples iff classified REPRESENTATIVE: valid (not deleted,
not red-flag), not pit-in/pit-out, no yellow/double-yellow/SC/VSC overlap,
not an outlier (>1.07x own-stint median, needs >=3 clean samples), duration
present. Every exclusion is recorded with its reason codes - nothing is
silently dropped.

## 2. Metrics

rolling_pace(N): mean of the trailing N eligible laps (chronological).
Requires exactly N available; otherwise None. Windows used: 3/5/10.

stint_average(S): mean eligible laps with stint window S.

median_pace(d): median eligible laps (robust to residual noise).

field_median: median across drivers of their median_pace; drivers without
samples are skipped.

pace_trend: OLS slope over trailing TREND_WINDOW=5 eligible laps, s per lap.
Negative = improving. Requires full window.

pace_delta_to_field: median_pace(d) - field_median.

## 3. Known limitations

- Fuel-load and track-evolution effects are NOT corrected in Phase 2
  (documented deferral); cross-stint comparisons therefore carry systematic
  drift that comparisons within a stint avoid.
- Pit-in detection depends on stint-boundary knowledge which may arrive late
  from some providers; such laps may temporarily count as flying until
  records land (retroactive stint assignment corrects the stint grouping,
  while pace eligibility for those specific laps is re-derived on demand).
- Clean-air v1 uses gap thresholds only (see METRIC_DEFINITIONS); it cannot
  see DRS detection zones or off-line traffic.
