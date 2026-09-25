# Phase 10.3 — Track Geometry: Position-Based Lap Alignment

## Status

**Engine built and proven on exact geometry. Real-data gate armed and
awaiting OpenF1 `/location` data.** Nothing here claims real-data
improvement yet — that claim is a falsifiable test that has not run on
real data.

## Why this phase exists (measured, not assumed)

The Phase 10.2 real-data audit (Sainz vs Russell, Singapore 2023 Q3)
showed speed-integrated distance placing the *same official sector lines*
4.3 m (S1) and 2.0 m (S2) apart between the two drivers. In a 78 kph
corner, 1 m of misalignment is 46 ms of fake delta, which is why the
reported max gain/loss were not reliable. It also showed a ~19 ms
start-offset bias from measuring elapsed time from each driver's first
telemetry sample.

## Design (implemented as already specified)

`docs/PHASE_10_LAP_SYNCHRONIZATION.md` ("Track coordinate model")
specified this before any code existed. It was implemented as written:

- **Self-referential centerline:** the reference path is the session's
  own reference lap (x, y), which in the committed fixture is the pole lap.
  Every car in a session shares that frame, so no external geometry and no
  cross-source calibration are involved.
- **Nearest-point-on-polyline projection** gives arc length along the
  shared path, using a windowed search (±40 segments, wrapping at the
  line) with a full-search fallback. That is linear, not quadratic.
- **Unwrapping:** a sample just before the line gets a negative fraction,
  not "end of lap".
- **Continuity guards, not smoothing:**
  - backward jitter under 0.2% of the path is held and marked MEDIUM;
  - larger backward jumps, or progress faster than 3× the lap's mean rate,
    are rejected (NONE);
  - a lateral offset over 1% of the path caps confidence at LOW;
  - a car sample inside a location-feed gap wider than 2 s is capped at
    LOW.
- **Pit:** pit laps are capped via the existing `LapClass`. There is no
  pit-lane geometry.

## The architectural seam — no second engine

`build_position_distance_trace` returns the existing `LapDistanceTrace`
with `distance_m = path fraction × lap_length_m`. Everything downstream —
`normalize_lap`, `synchronize_drivers`, `delta_t`, `analyze_delta` — is
reused unchanged. Three minimal, backward-compatible engine changes made
that possible:

1. `LapDistanceTrace.time_origin` (default `None` keeps 10.1B behaviour).
   Position distance is measured from the physical timing line, so its time
   origin is the official lap start. This removes the start-offset bias.
2. `compare_traces(trace_a, trace_b, ...)`: the comparison with the
   distance source factored out. `compare_driver_laps` now calls it.
3. `rollup_trace_confidence`: the 10.1B confidence roll-up lifted into a
   shared helper, so the position path reuses it rather than copying it.

All 77 existing 10.1B/10.1C/10.2/real-pair tests passed unchanged after
these refactors.

**Unit-free.** OpenF1 states an arbitrary x/y origin and no unit.
Everything works in fractions of the reference path. The real-data audit
will *measure* the unit (reference path length ÷ cited lap length) rather
than assume it.

## Evidence so far

- 16 exact-geometry tests (a 400-unit square path):
  - arc length, projection on and off the path;
  - window search equal to global search, and performance;
  - unwrapping at the line, jitter hold, backward-jump and impossible-rate
    rejection, and continuity resuming from the last accepted point;
  - no extrapolation outside location coverage, and time_origin;
  - location-gap downgrade;
  - **the reason for the phase:** a 2.8% under-reading speed channel
    produces ~0.57 s of fake delta by speed integration, and exactly 0 by
    position.
- Mutation-checked. Each of these fails the suite: ignoring time_origin,
  not holding jitter, no rate guard, speed as the distance source, and no
  location-gap cap. The "no window wrap" mutant survives, **by design**:
  edge-fallback keeps results correct and the wrap only saves a full scan
  per lap. This is recorded as a performance optimisation, not a
  correctness claim.
- The real-data gate (`tests/test_real_pair_position_alignment.py`, 5
  tests, skipped until location data exists) was dry-run on a synthetic
  OpenF1-shaped pair in `/tmp` (deleted, never committed). It passes when
  B's speed channel under-reads by 2%. It **fails** when B's position feed
  lags 20 m or sits in a different frame, which shows it can fail.

## What the real gate claims (falsifiable)

1. The location rows pass the identity guard.
2. Both drivers share the reference frame: B's median offset from A's path
   is under 1% of its length, and fewer than 5% of positions are rejected.
3. **Position places the official S1 and S2 lines closer together across
   the two drivers than speed integration did.**
4. The position comparison never runs distance backwards and never claims
   gain or loss without data.

If (3) fails on real data, that is a real finding about OpenF1 position
quality. It must not be tuned away.

## Closing the gate (locally, outside a live F1 session)

```powershell
cd backend
.\.venv\Scripts\python.exe ..\scripts\fetch_real_driver_pair.py --session-key 9161 --driver-a 55 --driver-b 63 --lap-length-m 4940 --lap-length-source "Wikipedia, 2023 Singapore Grand Prix: course length 4.940 km (Marina Bay 2023-2024 layout)"
.\.venv\Scripts\python.exe -m pytest tests\test_real_pair_position_alignment.py tests\test_real_pair_acceptance.py -v
.\.venv\Scripts\python.exe ..\scripts\audit_real_pair.py
```

Script v2 re-fetches the same laps plus `/location`. The 10.2 gate must
still show 9 passed / 1 skipped on the refreshed fixture.

## Known limitations

- Real-data improvement is unproven until the gate runs.
- The thresholds (0.2% backtrack, 3× rate, 1% offset) are reasoned
  defaults. The audit reports how often real data triggers each, for
  calibration.
- The reference path is one lap's line. B's projection measures progress
  along A's line, not B's own line length. That is correct for alignment,
  and it is why absolute metres come from fraction × cited length.
- There is no pit-lane geometry, no corner naming, and no external
  circuit maps. Those are later, calibration-gated work, as the design doc
  specifies.
- Segmentation calibration and alignment-aware confidence (Phase 10.2
  open issues 2 and 4) are not addressed yet. Real position data is what
  they need.
