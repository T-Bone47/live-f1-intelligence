# Phase 10.2 — Engineering Telemetry Comparison & Delta Analysis

Status: implemented and tested. Describes what exists.

## Scope actually covered

The Phase 10.2 prompt received for this work ended mid-way through
Section 9 (gain/loss segmentation). Sections 0–9 are implemented as
written. Nothing from later sections was guessed at.

## Chain

```
10.1B engine -> 10.1C DriverLapComparison -> 10.2 analyze_delta()
```

`backend/app/analysis/delta_analysis.py` reads the grid that
`synchronize_drivers` already built. It does not re-synchronize anything,
add a confidence system, or reclassify laps.

## Sign convention (Section 8)

Verified in `app/analysis/lap_distance.py` source (`return ea - eb`) and
inherited unchanged: `delta_t = elapsed_A - elapsed_B`, negative means A
is ahead. A test asserts every analysis delta equals 10.1C's `delta_at`.

## Delta model (Section 7) — `DeltaSample`, one per grid point

- `delta_t_s`, and both drivers' lap-relative elapsed time
- both drivers' speed, throttle, brake, rpm, gear, DRS (`a`, `b`)
- `continuous_delta`: A − B for speed/throttle/brake/rpm
- `discrete_differs`: gear and DRS compared for **equality only** — never
  subtracted (a test asserts no `gear`/`drs` key ever appears in
  `continuous_delta`)
- `None` wherever either driver lacks coverage

## Delta-curve summary (Section 8) — `DeltaAnalysis`

`delta_at_start_s`, `delta_at_finish_s`, `max_gain_s`/`max_gain_x` (most
negative delta — A's biggest lead), `max_loss_s`/`max_loss_x` (most
positive). `max_gain_s` is `None` if A never led; `max_loss_s` is `None`
if A never trailed — no gain or loss is reported that didn't happen. Ties
resolve to the first occurrence. Delta at an arbitrary distance reuses
10.1C's `delta_at(analysis.comparison, x)` rather than a second copy.

## Segmentation (Section 9) — `segment_delta_curve`, O(n)

1. Each grid step is labelled by the sign of the delta change:
   GAINING (delta decreasing), LOSING (increasing), STABLE (unchanged), or
   NO_DATA (either driver has no coverage — gaps are shown, never bridged).
2. Consecutive equal labels merge.
3. GAINING/LOSING runs with net change below `min_segment_change_s`
   become STABLE, then equal neighbours merge again.
4. A GAINING segment that begins with A behind (delta > 0) is RECOVERING.

Each `DeltaSegment` carries its distance range, delta at both ends, net
`time_change_s`, mean continuous telemetry deltas, the fraction of points
where gear/DRS differ, and a confidence (worst point in the region;
NO_DATA is always `NONE`).

### Threshold evidence

`TIMING_RESOLUTION_S = 0.001`: F1 timing — including the OpenF1 `/laps`
data used in this repo's tests (e.g. `lap_duration: 91.743`) — resolves to
the thousandth. Changes smaller than that are below the sport's own
timing resolution. This is a resolution floor, **not** a telemetry-noise
model; a noise-calibrated threshold needs real complete two-driver laps,
which the repository doesn't have. It is a parameter, not a hard-coded
constant.

## Tests — `backend/tests/test_delta_analysis.py`, 12 tests

Expected values are derived by hand from piecewise-constant speed profiles
(e.g. A 100 m/s for 500 m then 41.67 m/s vs B constant 66.67 m/s gives
delta −5x then 9x − 7: −2.5 s at x = 0.5, +2.0 s at the finish). Covers
the delta curve, max gain/loss, GAINING→LOSING, LOSING→RECOVERING,
STABLE, NO_DATA, sub-resolution noise, per-segment telemetry, discrete
fields, sign-convention inheritance, determinism, and the real OpenF1
fixture (which honestly yields one NO_DATA region and no gain/loss claims).

A mutation check was run before committing: flipping the gain/loss sign,
removing RECOVERING, removing the noise threshold, and subtracting gear
instead of comparing it each make the suite fail.

## Known limitations

- No real pair of complete two-driver laps exists in the repository, so
  all non-trivial numeric behaviour is proven on synthetic profiles.
- The threshold is a resolution floor, not a noise model.
- A GAINING region split by a sub-threshold STABLE blip stays split; it is
  not merged back into one GAINING region.
- No API endpoint, no corners, no geometry, no explanations — all out of
  Phase 10.2's own boundary.
