# Phase 10.1C — Driver A/B Lap Comparison

Status: implemented and tested. Describes what exists, nothing aspirational.

## What it is

`backend/app/analysis/lap_comparison.py` — a thin orchestration service
that turns two drivers' laps into one ready-to-use comparison:

```
real telemetry (A, B)
  -> build_lap_distance_trace   (10.1B)
  -> normalize_lap              (10.1B, same lap_length_m for both)
  -> synchronize_drivers        (10.1B, common grid, session check)
  -> delta_t                    (10.1B, lap-relative elapsed time)
  -> DriverLapComparison
```

It reimplements none of those steps. Every one delegates to
`app.analysis.lap_distance` (Phase 10.1B). The only shared helper that
had to change was `_confidence_rank`, renamed to the public
`confidence_rank` so this module can reuse it instead of writing a second
confidence ordering.

## Public surface

- `compare_driver_laps(lap_a, samples_a, lap_class_a, lap_b, samples_b,
  lap_class_b, lap_length_m, step=0.001) -> DriverLapComparison`
- `delta_at(comparison, x) -> float | None`
- `DriverLapComparison`: both traces, the `SynchronizedComparison`,
  `delta_at_start`, `delta_at_finish`, and an overall `confidence`.

## Semantics

- **Delta sign convention** (inherited from 10.1B's `delta_t`, not
  redefined): `elapsed_A(x) - elapsed_B(x)`. Negative means A reached `x`
  sooner — A is ahead at that point on track.
- **Overall confidence** is the worse of the two traces. A clean pole lap
  compared against a degraded pit-out lap is not a HIGH-confidence
  comparison. Uses the existing `Confidence` system, no second one.
- **Different sessions** are refused (`ValueError`), via 10.1B's existing
  check — not re-implemented here.
- **No coverage, no value.** If either driver's telemetry does not reach
  distance `x`, `delta_at(x)` is `None`. See the bug fix below.
- `lap_length_m` is caller-supplied. There is still no circuit geometry in
  this project to derive it from, and none is invented here.

## Bug found and fixed in the 10.1B engine during this phase

Writing the first 10.1C test exposed a real defect in 10.1B's
`resample_common_grid`: grid points beyond the last real sample were
**clamped** to that sample. A driver whose integrated distance stopped at
83% of the lap therefore reported an elapsed time, speed, and gear at the
finish line — a fabricated delta. It is now fixed: grid points outside a
trace's actually-covered distance range return `None` values and
`Confidence.NONE`. A `1e-9` tolerance prevents a trace that genuinely
reaches `x = 1.0` from being cut off by float rounding. A dedicated
regression test (`test_grid_points_beyond_trace_coverage_are_none_not_clamped`)
covers it. No existing 10.1B test depended on the old clamping behavior.

## Real data

- **Driver 55, session 9159** (the Phase 10.1A fixture): real OpenF1
  telemetry through the real `to_car_sample()` mapper, used as one side of
  a comparison. It is a genuinely stationary engine-warmup sequence, so it
  integrates to 0m; the test asserts the comparison therefore has **no**
  finish-line delta, rather than inventing one.
- **Driver 63, session 9161, lap 8**: a real, complete `Lap` record
  fetched live from OpenF1's `/laps` endpoint (real sector times summing
  to the real 91.743s lap duration). No matching real `car_data` could be
  obtained for it — every fetch attempt for other drivers/sessions
  returned the same cached driver-55 response. The test uses this real lap
  with zero samples and asserts the engine reports `Confidence.NONE` with
  no fabricated trace.

**Honest gap:** there is still no real pair of complete, continuous laps
from two drivers in this repository. The A/B comparison mechanics are
proven with synthetic data (exact, hand-verifiable numbers — e.g. at
x=0.5 A took 5.0s, B 6.0s, delta exactly -1.0s); the real-data tests prove
the real mapping path and honest no-data handling, not a real driver-vs-
driver result.

## Tests

`backend/tests/test_lap_comparison.py` — 7 tests (5 mechanics, 2 real
data), plus 1 regression test added to `test_lap_distance_sync.py`.

## Not in this phase

No API endpoint, no max-gain/max-loss scan, no gain/loss segmentation —
that is Phase 10.2's stated scope and was deliberately left for it.
