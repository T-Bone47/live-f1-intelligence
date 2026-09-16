# PHASE 10 — LAP SYNCHRONIZATION & TRACK COORDINATES

> Rules 6 and 7 combined: synchronization is fundamentally about the
> distance axis, and Rule 7's centerline is what makes that axis
> meaningful across drivers, not just within one driver's own data.

## Distance derivation

No endpoint or model in this codebase currently exposes distance along a
lap (confirmed absent — `PHASE_10_DATA_AVAILABILITY.md`). Two candidate
methods exist; only one is buildable today without a new dependency:

**Primary: trapezoidal integration of `speed_kph` over time.**
`distance(t) = distance(t_prev) + avg(speed(t_prev), speed(t)) × (t − t_prev)`,
converted to m/s. This is the same approach FastF1 itself uses for its
own `Distance` channel (DOCUMENTED, Rule 2 research) — not invented here.
Buildable immediately: `speed_kph` is OBSERVED, real, and already flowing
through the working OpenF1 path. No circuit geometry dependency.

**Secondary, once geometry exists: x/y projection onto a reference path**
(§ below) — useful as a cross-check against wheel-spin or lockup
distortion in the pure speed integral, not a replacement for it.

## Normalization

Two drivers on "the same lap" cover slightly different physical ground
distance depending on racing line. Aligning by raw integrated meters
would misalign corners between drivers. The comparison axis must be
**percentage of total lap distance (0-100%)**, not absolute meters.

## Lap start / end

`Lap.started_at` + `duration_s` gives real boundaries (both OBSERVED,
real fields). One edge case worth flagging rather than assuming clean: a
red-flag restart or formation lap could leave a gap or overlap between
one lap's computed end and the next lap's stated start — needs an
explicit continuity check, not an assumption.

## Interpolation

Raw samples are irregular (~3.5Hz native, OBSERVED/DOCUMENTED). A
distance-aligned comparison needs both drivers resampled onto a **common
distance grid** (e.g., every 0.1% of lap distance) via linear
interpolation — this is what makes delta calculation possible at all,
since real samples from two drivers essentially never land at the same
distance simultaneously.

**Gap handling**: naive interpolation across a genuinely large gap would
smooth away exactly the transient (a lockup, a spin) someone most wants
to see. Define a real gap threshold; beyond it, mark that distance span
low-confidence/estimated rather than silently smoothing over it — matches
this codebase's consistent pattern of honest degradation over confident
fabrication (evident throughout Phase 9's fixes: rainfall as a boolean
rather than a fabricated percentage, circuit geometry honestly labeled
unavailable rather than invented, etc.).

## Invalid laps

`is_pit_out_lap` is genuinely wired (OBSERVED — populated from both
OpenF1's own field and FastF1's `PitOutTime`, persisted, consumed
downstream in `analysis/laps.py`) — usable now to exclude out-laps from
default "best lap" suggestions. `deleted` is a real field but **never set
anywhere in this codebase** (confirmed by direct search, not assumed) —
its own comment says "future phase." The comparison feature must not
treat "no deleted laps found" as "no invalid laps exist" — that's a false
negative waiting to happen until track-limits-deletion detection is
actually built. `race_control.qualifying_phase` (DOCUMENTED upstream on
OpenF1, not present in this codebase) would help exclude wrong-segment
laps once wired — a direct, concrete answer to the `QualifyingCutLine`
Q1/Q2/Q3 gap identified in Phase 9, not implemented here.

## Sector boundaries

`sector1_s`/`sector2_s`/`sector3_s` project directly onto the derived
distance axis (boundary = distance at elapsed-time = cumulative sector
time) — no new geometry needed for sector-level alignment. True
corner-by-corner granularity still needs the track-coordinate work below;
sectors alone give 3 segments per lap, not individual corners.

---

## Track coordinate model

### The honest problem
Two real geometry sources exist (`PHASE_10_DATA_AVAILABILITY.md`), but
neither has been verified to align with OpenF1's telemetry frame.
OpenF1's own docs say its x/y/z origin is "arbitrary" — arbitrary
relative to what is not stated, and there is no evidence it's the *same*
arbitrary origin MultiViewer/FastF1's `circuit_info` uses for the same
circuit. Overlaying unverified geometry onto real car positions risks
producing a confidently-wrong visual — the exact failure mode this
codebase has repeatedly guarded against elsewhere (weather, circuit
geometry's existing honest "unavailable" fallback, etc.).

### Primary approach: self-referential centerline
Build the centerline from the *session's own* reference-lap telemetry —
e.g., the pole-sitter's clean Q3 lap's own (x, y) trace. Every other
car's telemetry in that same session is guaranteed already in that exact
frame. **Zero cross-source alignment risk**, because no second source is
involved. Available the moment the persistence wiring fix (architecture
doc, §4) lands.

### External geometry: a calibration-gated enhancement layer
MultiViewer/FastF1's `circuit_info` and `bacinger/f1-circuits` become
useful for corner names, marshal sectors, and a track outline visible
before any telemetry loads — but only behind an explicit calibration
step: fit a rigid transform (rotation + translation, possibly scale)
between the reference-lap centerline and the external source, using
documented anchor points if either source states one, or curve-matching
otherwise. Treat the fit's residual error as a displayed confidence
signal, not a silent pass/fail. Until calibrated and checked against a
real captured lap, external geometry stays presentation-only — a
background image or nearby label, not something car markers are
mathematically projected onto.

### Distance-along-track for any car (not just the one that defined the centerline)
Standard nearest-point-on-polyline projection: for each sample, find the
closest centerline segment, compute the perpendicular projection, take
the centerline's cumulative arc-length to that point. Complementary to
the speed-integration method above, not a duplicate — this gives *any*
car (including one running off-line) a position relative to the shared
reference path, and can cross-validate the speed-integrated figure.

### Direction
Falls out for free: the centerline polyline's point order already
encodes travel direction (built from a real lap, start to finish).
Heading at a projected point is the tangent of the nearest segment.

### Noisy points
Distance-continuity check: if a projected distance implies an impossible
instantaneous speed relative to neighboring samples, treat it as an
outlier. Same honest-degradation philosophy as gap handling above — small
noise gets smoothed, a genuinely bad stretch gets marked estimated.

### Pit lane
Physically a separate path that branches off and rejoins — naive
centerline projection would show a pitting car "stuck" at whatever
main-straight point is geometrically nearest, which is confidently wrong,
not just imprecise. `LeaderboardRow.in_pit` is real and already used
elsewhere in this codebase (`TimingTower`, `CircuitMap`) — suppress
centerline projection entirely while `in_pit` is true, don't approximate.
