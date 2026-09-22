# Phase 10.1B — Lap Distance Synchronization

Status: implemented and tested. Describes what is actually built, not the
aspirational full feature set — see "Known limitations" and "Future
extension" at the end for what this deliberately does not cover yet.

## 1. Problem

Telemetry is fundamentally timestamp-based (a sample every ~0.29s at
OpenF1's native rate). Comparing two drivers by timestamp compares "what
were they doing at the same wall-clock instant", which is meaningless once
they're not literally side by side — what matters for "where did A gain or
lose time to B" is comparing them at the same *point on the circuit*, not
the same instant. This phase builds the coordinate transform from
timestamp to distance-along-lap that makes that comparison possible.

## 2. Existing telemetry model (unchanged)

`app.core.models.TelemetryCarSample`: `session_id`, `driver_number`, `ts`,
`rpm`, `speed_kph`, `gear`, `throttle_pct`, `brake_pct`, `drs`,
`provenance`. `app.core.models.Lap`: `started_at`, `duration_s`,
`sector1_s`/`sector2_s`/`sector3_s`, `is_pit_out_lap`, `deleted` (never
actually set anywhere — reconfirmed by direct search this phase, not
assumed from the architecture doc). Nothing in this phase changes these
models, the ingestion pipeline, persistence, or the telemetry REST API —
this is a pure computation layer, same architectural shape as
`app.analysis.sectors.SectorEngine` and `app.analysis.laps.LapClassifier`.

## 3. Distance integration method

Trapezoidal integration of `speed_kph` (converted to m/s) over consecutive
samples within a lap's telemetry window — the same approach documented in
`docs/PHASE_10_LAP_SYNCHRONIZATION.md` (and the same one FastF1 uses for
its own Distance channel; not invented here):

```
v0_mps, v1_mps = speed_kph[i-1]/3.6, speed_kph[i]/3.6
distance_increment_m = max(0, (v0_mps + v1_mps) / 2 * dt)
distance[i] = distance[i-1] + distance_increment_m
```

`max(0, ...)` is a defensive floor against a physically-impossible negative
speed reading corrupting the running total — not a correction applied to
plausible-but-noisy data.

## 4. Units

Every distance field carries an explicit `_m` suffix (metres) —
`distance_m`, `lap_length_m`, `total_distance_m` — matching this project's
existing convention (`wind_speed_mps`, `speed_kph`) of never leaving a unit
implicit. `normalized_distance` is a dimensionless fraction of lap length,
not a second physical unit.

## 5. Gap threshold

`MAX_GAP_S = 2.0`, evidence-based rather than an arbitrary round number:
computed directly from `scripts/fixtures/real-openf1-9159`'s real OpenF1
`car_data` (see `tests/test_lap_distance.py::test_gap_threshold_is_grounded_in_real_data`,
which recomputes this from the raw fixture on every run rather than trusting
a comment to stay accurate). That fixture's 38 real inter-sample deltas:
minimum 0.16s, median 0.28s (matches the ~3.5Hz native rate documented
elsewhere in this project), maximum-while-still-continuous 0.96s. The next
real gap in that same fixture is 1202.9s — three orders of magnitude
larger, nothing in between. 2.0s sits roughly 2x the largest genuinely
continuous real interval observed: comfortably above ordinary jitter or an
occasional dropped sample, nowhere near an actual discontinuity.

## 6. Invalid-data behavior

- **Timestamp regression** (`dt < 0`): contributes zero distance, flagged
  `Confidence.NONE`. Not "corrected" by guessing the intended order.
- **Duplicate timestamp** (`dt == 0`): contributes exactly zero distance
  (mathematically exact for a zero-width interval, not an approximation),
  flagged `Confidence.MEDIUM` as a data-quality observation.
- **Missing speed** on either end of an interval: cannot integrate that
  interval at all; distance held flat, flagged `Confidence.NONE`.
- **Gap above `MAX_GAP_S`**: still integrated (the best available estimate)
  but flagged `Confidence.LOW` — never presented as equally precise to a
  normal-rate interval, and no fabricated intermediate samples are inserted.

## 7. Lap boundary behavior

Telemetry is filtered to `[lap.started_at, lap.started_at + duration_s]`
(inclusive on both ends — a sample landing exactly on a boundary is
genuinely part of that instant, not silently dropped). A lap with no
`duration_s` (in progress, or never reported) returns an explicitly empty,
`NONE`-confidence trace rather than guessing an end time. Each lap's
cumulative distance always starts fresh at 0 — verified this cannot leak
across `Lap N -> Lap N+1` even when the same underlying sample stream is
shared.

**Coverage check**, added during this phase's own final review (Phase 22):
sample *count* alone doesn't guarantee samples actually span the lap — 15
densely-packed samples covering only the first 5 seconds of a 60-second lap
would otherwise look identical to a real complete lap. `LapDistanceTrace.is_complete`
is `False` whenever the first or last sample sits more than `MAX_GAP_S` from
the lap's actual start/end, and incompleteness caps confidence the same way
an internal gap does.

## 8. Normalization

`normalized_distance = distance_m / lap_length_m`. Deliberately **not**
clamped into `[0, 1]`: if raw integrated distance exceeds `lap_length_m`
(integration drift, wheel-spin-inflated speed, a slightly-wrong length
estimate), that overshoot is real information about the estimate's
quality. `LapDistanceTrace.has_overshoot` and each point's `is_overshoot`
flag this explicitly; an otherwise-`HIGH`-confidence trace with overshoot
is downgraded to `MEDIUM`, not silently presented as clean. Zero or
missing `lap_length_m` leaves every point's `normalized_distance` as
`None` and confidence `NONE` rather than dividing by zero or fabricating a
length.

## 9. Interpolation semantics

`resample_common_grid` builds a common grid `x = 0, step, 2*step, ..., 1.0`
via `bisect`-based O(log n) bracket lookup per grid point (not a linear
scan — this may run over long telemetry streams).

- **Continuous fields** (`speed_kph`, `throttle_pct`, `brake_pct`, `rpm`):
  linear interpolation between the two bracketing real points.
- **Discrete fields** (`gear`, `drs`): step/hold-last-value — the exact
  value of the last real point at or before `x`. Never blended: gear 5 to
  6 never produces gear 5.43, and DRS off/on never produces an
  intermediate continuous value.

## 10. Delta calculation

`delta_t(sync, x)` returns `elapsed_A(x) - elapsed_B(x)`, where `elapsed`
is lap-relative time (seconds since each driver's own lap start) —
**never** a subtraction of raw wall-clock timestamps between drivers, which
would be meaningless once two laps started at different real-world
instants (tested explicitly with two laps 5 real hours apart: identical
speed profiles produce `delta_t ≈ 0` everywhere, proving lap-relative time
was used, not `timestamp_A - timestamp_B`, which would have been ~18000s).

## 11. Confidence / provenance

Reuses this project's one existing confidence system throughout —
`app.analysis.confidence.Confidence` (`HIGH`/`MEDIUM`/`LOW`/`NONE`) and
`DerivedProvenance` — rather than introducing a second, parallel
vocabulary. A trace's overall confidence is the **worse** of (a) its worst
individual point and (b) a ceiling from lap classification / coverage /
sample count — found and fixed during final review that the first
implementation had this backwards in one case (a pit lap with an
independently-bad point was capped at the milder classification-based
`LOW` rather than correctly reflecting a worse point-level `NONE`).

## 12. Pit-lane limitations

`LapClass.PIT_IN`/`PIT_OUT`/`IN_LAP` laps get their own `is_pit_lap` flag
and are capped at `LOW` confidence regardless of how cleanly their
telemetry happens to integrate — a pit lane lap can have perfectly smooth
speed data and still not be a representative racing lap. No pit-lane
geometry, track projection, or coordinate work is implemented — that
remains for a future phase with real circuit geometry (see below).

## 13. API implications

None. No new or changed endpoints. This is a pure computation module
(`app/analysis/lap_distance.py`) callable directly; per this phase's own
scope, exposing it via a REST endpoint is deferred to whichever later
phase actually needs it (Phase 10.1C, driver comparison).

## 14. Test coverage

84 new tests across four files (`test_lap_distance.py`,
`test_lap_distance_sync.py`, `test_lap_distance_real_fixture.py` — plus
one existing-suite regression check), covering all 22 categories from the
phase's test plan: constant/variable-speed integration, km/h conversion,
timestamp ordering/duplicates/regression, missing speed, large gaps,
monotonicity, lap reset, normalization (including overshoot and
zero-length), incomplete laps/insufficient telemetry, driver A/B sync,
continuous and discrete interpolation, delta-time, sector-boundary
compatibility, pit/invalid-lap handling, confidence propagation,
determinism, and property/invariant checks across varied synthetic
inputs. Three tests specifically exercise the real `real-openf1-9159`
fixture: real OpenF1 data mapped through the real `to_car_sample`
function, a real ~10-second stationary sequence integrating to genuinely
zero distance, and the real ~27-minute gap in that fixture correctly
triggering low-confidence (not smoothed-over) integration — with the
expected values computed from the fixture itself in the test, not
hardcoded.

## 15. Known limitations

- `lap_length_m` must be supplied by the caller — this module does not
  derive circuit length itself (no circuit geometry exists yet in this
  project; inventing one would be exactly the fabrication this phase's
  master prompt forbids).
- No REST endpoint exists yet; this is a library, not a feature surface.
- The confidence roll-up and coverage-completeness checks are per-lap;
  they don't yet reason about patterns *across* laps (e.g., a driver whose
  every lap this session has degraded telemetry).
- `synchronize_drivers` requires both traces from the same `session_id`
  (enforced — raises rather than silently comparing across circuits) but
  does not yet check both laps used the same `lap_length_m`, which a
  caller could mismatch by passing inconsistent values into `normalize_lap`.

## 16. Future extension to track geometry

This phase produces a normalized `[0, 1]` distance coordinate with no
notion of *where* on the circuit that corresponds to physically. A later
phase (10.1D per the existing roadmap) can attach real circuit centerline
/ corner geometry to this same coordinate — nothing here needs to change
for that; `normalized_distance` is exactly the join key such a system
would need.
