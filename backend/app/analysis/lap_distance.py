"""Phase 10.1B: lap-distance synchronization engine.

Transforms timestamp-based telemetry (speed, throttle, brake, ...) into a
distance-along-lap coordinate, so two drivers' telemetry can be compared at
the same point on track rather than the same wall-clock instant.

Algorithm: trapezoidal integration of speed_kph over time, converted to
m/s - documented in docs/PHASE_10_LAP_SYNCHRONIZATION.md as "the same
approach FastF1 itself uses for its own Distance channel" and confirmed
there as buildable without any new dependency (speed_kph is real,
OBSERVED telemetry already flowing through the OpenF1 path). Not invented
here.

Pure computation over already-persisted/streamed data (TelemetryCarSample,
Lap) - same architectural shape as app.analysis.sectors.SectorEngine and
app.analysis.laps.LapClassifier. No new database schema, no changes to
the ingestion pipeline, persistence, or the telemetry REST API. Reuses
this project's one existing confidence system (app.analysis.confidence,
Confidence, DerivedProvenance) rather than inventing a second one, and
LapClassifier's existing LapClass rather than reclassifying laps itself.

Units are always explicit: every distance field carries an _m suffix
(metres), matching this project's existing convention of never mixing
units silently (e.g. wind_speed_mps, speed_kph both name their unit).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.analysis.common.models import Confidence, DerivedProvenance, LapClass
from app.core.models import Lap, TelemetryCarSample

CALC_VERSION = "lap-distance-1.0.0"

# Evidence for this threshold (not an arbitrary round number): computed
# directly from tests/fixtures/real-openf1-9159's real OpenF1 car_data -
# see tests/test_lap_distance.py::test_gap_threshold_is_grounded_in_real_data,
# which recomputes this from the raw fixture on every run rather than
# trusting this comment to stay accurate. 38 real inter-sample deltas in
# that fixture: minimum 0.16s, median 0.28s (matches this project's
# documented ~3.5Hz native OpenF1 rate in PHASE_10_LAP_SYNCHRONIZATION.md/
# PHASE_10_DATA_AVAILABILITY.md), maximum-while-still-continuous 0.96s.
# The next real gap in that same fixture is 1202.9s - three orders of
# magnitude larger, with nothing in between. MAX_GAP_S sits roughly 2x the
# largest genuinely-continuous real interval observed: comfortably above
# ordinary jitter or an occasional dropped sample, nowhere near the actual
# discontinuities in real data.
MAX_GAP_S = 2.0

MIN_SAMPLES_FOR_HIGH_CONFIDENCE = 10

# Interpolation semantics per telemetry field. Continuous fields are
# linearly interpolated on the common distance grid; discrete/categorical
# fields use step (hold-last-value) semantics instead - Phase 8's explicit
# requirement: gear must never become 6.37, DRS must never become an
# arbitrary continuous value.
CONTINUOUS_FIELDS = ("speed_kph", "throttle_pct", "brake_pct", "rpm")
DISCRETE_FIELDS = ("gear", "drs")


@dataclass(frozen=True)
class DistancePoint:
    """One telemetry sample's position on the distance-along-lap axis.

    Carries the other telemetry fields alongside distance so a caller
    doing driver-to-driver interpolation (resample_common_grid,
    synchronize_drivers) has everything needed from one structure, rather
    than having to keep a second, parallel TelemetryCarSample list in
    sync with these points by index.

    normalized_distance is None until a lap_length_m is known (see
    normalize_lap) and is deliberately NEVER clamped into [0, 1] by that
    function when the raw integrated distance exceeds lap_length_m -
    overshoot is real integration error (speed noise, a slightly-wrong
    lap_length_m estimate, wheel spin) and clamping it away would silently
    destroy the evidence that something is off. is_overshoot flags this
    per-point instead.
    """

    ts: datetime
    distance_m: float
    normalized_distance: float | None
    speed_kph: float | None
    confidence: Confidence
    gap_s: float | None  # dt from the previous sample; None for the first point
    is_overshoot: bool = False
    throttle_pct: float | None = None
    brake_pct: float | None = None
    rpm: int | None = None
    gear: int | None = None
    drs: int | None = None


@dataclass
class LapDistanceTrace:
    """A full lap's telemetry, integrated onto the distance axis."""

    session_id: str
    driver_number: int
    lap_number: int
    points: list[DistancePoint] = field(default_factory=list)
    total_distance_m: float | None = None
    lap_length_m: float | None = None
    lap_class: LapClass | None = None
    is_pit_lap: bool = False
    is_complete: bool = False  # telemetry actually covers the lap's start-to-end window
    confidence: Confidence = Confidence.NONE
    has_overshoot: bool = False
    provenance: DerivedProvenance | None = None


def _to_mps(speed_kph: float) -> float:
    return speed_kph / 3.6


def integrate_distance(samples: list[TelemetryCarSample]) -> list[DistancePoint]:
    """Trapezoidal integration of consecutive samples' speed_kph over time.

    Guarantees, by construction rather than by post-hoc correction:
    - distance_m is never negative and never decreases point-to-point
      (each increment is max(0, ...); real speed_kph should never be
      negative, but a single malformed reading cannot corrupt the running
      total into going backward).
    - a timestamp regression (dt < 0) contributes zero distance and is
      flagged Confidence.NONE - the interval is not integrated at all,
      not "corrected" by guessing the intended order.
    - a duplicate timestamp (dt == 0) contributes exactly zero distance
      (mathematically exact, not an approximation) but is flagged
      Confidence.MEDIUM as a data-quality observation - two samples at
      the identical instant is unusual even though the zero-width
      interval's math is not in question.
    - a missing speed_kph on either end of an interval cannot be
      integrated; distance is held flat and the point is flagged
      Confidence.NONE rather than assuming a speed.
    - an interval wider than MAX_GAP_S is still integrated (it is the
      best available estimate) but flagged Confidence.LOW - never
      silently presented as equally precise to a normal-rate interval,
      and never smoothed away by inserting fabricated intermediate
      samples.

    Does not sort or reorder samples - callers are expected to supply
    them in the order they actually arrived; silently reordering would
    hide exactly the anomaly this function is meant to surface.
    """
    if not samples:
        return []

    points: list[DistancePoint] = []
    cum = 0.0
    prev: TelemetryCarSample | None = None

    for s in samples:
        extra = _extra_fields(s)
        if prev is None:
            conf = Confidence.HIGH if s.speed_kph is not None else Confidence.NONE
            points.append(DistancePoint(ts=s.ts, distance_m=0.0, normalized_distance=None,
                                         speed_kph=s.speed_kph, confidence=conf, gap_s=None,
                                         **extra))
            prev = s
            continue

        dt = (s.ts - prev.ts).total_seconds()

        if dt < 0:
            points.append(DistancePoint(ts=s.ts, distance_m=cum, normalized_distance=None,
                                         speed_kph=s.speed_kph, confidence=Confidence.NONE,
                                         gap_s=dt, **extra))
            prev = s
            continue

        if prev.speed_kph is None or s.speed_kph is None:
            points.append(DistancePoint(ts=s.ts, distance_m=cum, normalized_distance=None,
                                         speed_kph=s.speed_kph, confidence=Confidence.NONE,
                                         gap_s=dt, **extra))
            prev = s
            continue

        if dt == 0:
            points.append(DistancePoint(ts=s.ts, distance_m=cum, normalized_distance=None,
                                         speed_kph=s.speed_kph, confidence=Confidence.MEDIUM,
                                         gap_s=0.0, **extra))
            prev = s
            continue

        v0, v1 = _to_mps(prev.speed_kph), _to_mps(s.speed_kph)
        increment = max(0.0, (v0 + v1) / 2.0 * dt)
        cum += increment
        conf = Confidence.LOW if dt > MAX_GAP_S else Confidence.HIGH
        points.append(DistancePoint(ts=s.ts, distance_m=cum, normalized_distance=None,
                                     speed_kph=s.speed_kph, confidence=conf, gap_s=dt, **extra))
        prev = s

    return points


def _extra_fields(s: TelemetryCarSample) -> dict:
    return {"throttle_pct": s.throttle_pct, "brake_pct": s.brake_pct,
            "rpm": s.rpm, "gear": s.gear, "drs": s.drs}


def build_lap_distance_trace(
    lap: Lap, samples: list[TelemetryCarSample], lap_class: LapClass | None = None,
) -> LapDistanceTrace:
    """Filter telemetry to one lap's window and integrate it.

    Window is [lap.started_at, lap.started_at + duration_s) - samples
    outside a lap's own timing window belong to a different lap (or no
    lap at all) and must not leak into this one's cumulative distance
    (Phase 6's explicit requirement).

    lap_class (from app.analysis.laps.LapClassifier, not reclassified
    here) directly caps confidence: PIT_IN/PIT_OUT/INVALID/OUTLIER laps
    never get upgraded to a clean high-confidence trace merely because
    their telemetry happened to integrate cleanly - a pit lane lap can
    have perfectly smooth speed data and still not be a representative
    racing lap.
    """
    session_id = lap.session_id
    driver_number = lap.driver_number
    is_pit_lap = lap_class in (LapClass.PIT_IN, LapClass.PIT_OUT, LapClass.IN_LAP)
    is_invalid = lap_class in (LapClass.INVALID, LapClass.OUTLIER)

    if lap.duration_s is None:
        # Lap never completed (in progress, or duration never reported) -
        # there is no defined window to filter telemetry into. Return an
        # explicitly empty, NONE-confidence trace rather than guessing an
        # end time.
        return LapDistanceTrace(
            session_id=session_id, driver_number=driver_number,
            lap_number=lap.lap_number, lap_class=lap_class, is_pit_lap=is_pit_lap,
            confidence=Confidence.NONE,
            provenance=_provenance(session_id, Confidence.NONE),
        )

    window_end = lap.started_at.timestamp() + lap.duration_s
    windowed = [s for s in samples
                if lap.started_at.timestamp() <= s.ts.timestamp() <= window_end]

    points = integrate_distance(windowed)
    total = points[-1].distance_m if points else None

    # Coverage: does the telemetry we actually have span close to the
    # lap's full start-to-end window, or does it stop early / start late?
    # A trace built from samples covering only the first half of a lap
    # must not look identical to one that genuinely covers the whole lap -
    # Phase 6's "a lap with insufficient telemetry must not be represented
    # as a high-confidence complete lap" applies to a coverage gap at
    # either end just as much as to gaps between samples in the middle.
    is_complete = False
    if points:
        start_gap = points[0].ts.timestamp() - lap.started_at.timestamp()
        end_gap = window_end - points[-1].ts.timestamp()
        is_complete = start_gap <= MAX_GAP_S and end_gap <= MAX_GAP_S

    if not points:
        base_confidence = Confidence.NONE
    else:
        worst_point = min((p.confidence for p in points), key=_confidence_rank)
        # A classification/coverage/sample-count issue is a CEILING, not an
        # override: it can only pull confidence down from what the points
        # themselves already show, never mask a worse point-level problem
        # (e.g. a pit lap that ALSO has missing-speed samples must not be
        # reported as merely LOW when some of its points are NONE).
        ceiling = Confidence.HIGH
        if is_invalid or is_pit_lap or not is_complete:
            ceiling = Confidence.LOW
        elif len(points) < MIN_SAMPLES_FOR_HIGH_CONFIDENCE:
            ceiling = Confidence.MEDIUM
        base_confidence = min((worst_point, ceiling), key=_confidence_rank)

    return LapDistanceTrace(
        session_id=session_id, driver_number=driver_number, lap_number=lap.lap_number,
        points=points, total_distance_m=total, lap_class=lap_class, is_pit_lap=is_pit_lap,
        is_complete=is_complete, confidence=base_confidence,
        provenance=_provenance(session_id, base_confidence),
    )


def normalize_lap(trace: LapDistanceTrace, lap_length_m: float | None) -> LapDistanceTrace:
    """Attach normalized_distance = distance_m / lap_length_m to every point.

    Deliberately does NOT clamp normalized_distance into [0, 1]: if the
    raw integrated distance exceeds lap_length_m (integration drift,
    wheel-spin-inflated speed, or a slightly-wrong lap_length_m), that
    overshoot is real information about the estimate's quality, not
    something to hide for a tidier-looking [0, 1] axis. has_overshoot on
    the returned trace flags this explicitly; each point past the
    overshoot point also carries is_overshoot=True.

    zero-length or missing lap_length_m: cannot normalize at all (would
    divide by zero or be meaningless) - returns the trace with
    normalized_distance left None on every point and confidence
    downgraded to NONE, rather than fabricating a lap_length_m.
    """
    if not lap_length_m or lap_length_m <= 0:
        trace.confidence = Confidence.NONE
        trace.lap_length_m = lap_length_m
        return trace

    new_points = []
    has_overshoot = False
    for p in trace.points:
        nd = p.distance_m / lap_length_m
        overshoot = nd > 1.0
        has_overshoot = has_overshoot or overshoot
        new_points.append(DistancePoint(
            ts=p.ts, distance_m=p.distance_m, normalized_distance=nd,
            speed_kph=p.speed_kph, confidence=p.confidence, gap_s=p.gap_s,
            is_overshoot=overshoot, throttle_pct=p.throttle_pct, brake_pct=p.brake_pct,
            rpm=p.rpm, gear=p.gear, drs=p.drs,
        ))
    trace.points = new_points
    trace.lap_length_m = lap_length_m
    trace.has_overshoot = has_overshoot
    if has_overshoot and trace.confidence is Confidence.HIGH:
        # Overshoot on an otherwise-clean lap is downgraded, not hidden -
        # the axis is still usable but the estimate is demonstrably imperfect.
        trace.confidence = Confidence.MEDIUM
    return trace


def _confidence_rank(c: Confidence) -> int:
    return {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1,
            Confidence.NONE: 0}[c]


def _provenance(session_id: str, confidence: Confidence) -> DerivedProvenance:
    return DerivedProvenance(
        session_id=session_id,
        calculated_at=datetime.now(UTC),
        calc_version=CALC_VERSION,
        confidence=confidence,
    )


@dataclass
class ResampledSeries:
    """One trace, resampled onto a common normalized-distance grid.

    elapsed_s is the lap-relative elapsed time at each grid point (seconds
    since this trace's own first point) - distinct from ts, which stays a
    wall-clock timestamp. delta_t between two drivers is computed from
    elapsed_s, never from subtracting their raw timestamps (Phase 9's
    explicit requirement: two drivers' laps started at different
    wall-clock instants, so timestamp_A - timestamp_B is not a lap-time
    delta at all).
    """

    grid_x: list[float]
    confidence: list[Confidence]
    elapsed_s: list[float | None]
    continuous: dict[str, list[float | None]]
    discrete: dict[str, list[int | None]]


def resample_common_grid(trace: LapDistanceTrace, step: float = 0.001) -> ResampledSeries:
    """Resample a normalized trace onto a common grid x = 0, step, 2*step, ..., 1.0.

    Only meaningful on a trace that has been through normalize_lap (points
    need normalized_distance). Points without it are skipped - resampling
    against an un-normalized trace would silently produce a meaningless
    grid rather than raising, so this filters them out explicitly instead.

    Continuous fields (speed_kph, throttle_pct, brake_pct, rpm) are
    linearly interpolated between the two bracketing points. Discrete
    fields (gear, drs) use step/hold-last-value semantics instead - taking
    the nearest preceding point's exact value, never blending two gears or
    two DRS states into a fractional in-between value that was never
    actually observed.

    Uses bisect for O(log n) bracket lookup per grid point rather than a
    linear scan (Phase 16: avoid O(n^2) synchronization on what may be a
    long telemetry stream).
    """
    usable = [p for p in trace.points if p.normalized_distance is not None]
    n_steps = round(1.0 / step) + 1
    grid_x = [round(i * step, 10) for i in range(n_steps)]

    if not usable:
        return ResampledSeries(
            grid_x=grid_x, confidence=[Confidence.NONE] * n_steps,
            elapsed_s=[None] * n_steps,
            continuous={f: [None] * n_steps for f in CONTINUOUS_FIELDS},
            discrete={f: [None] * n_steps for f in DISCRETE_FIELDS},
        )

    xs = [p.normalized_distance for p in usable]
    t0 = usable[0].ts
    elapsed = [(p.ts - t0).total_seconds() for p in usable]

    continuous_out: dict[str, list[float | None]] = {f: [] for f in CONTINUOUS_FIELDS}
    discrete_out: dict[str, list[int | None]] = {f: [] for f in DISCRETE_FIELDS}
    elapsed_out: list[float | None] = []
    conf_out: list[Confidence] = []

    continuous_vals = {f: [getattr(p, f) for p in usable] for f in CONTINUOUS_FIELDS}

    for x in grid_x:
        if x <= xs[0]:
            lo = hi = 0
        elif x >= xs[-1]:
            lo = hi = len(xs) - 1
        else:
            hi = bisect.bisect_right(xs, x)
            lo = hi - 1

        conf_out.append(usable[lo].confidence if lo == hi
                         else min((usable[lo].confidence, usable[hi].confidence),
                                  key=_confidence_rank))
        elapsed_out.append(_lerp(xs, elapsed, lo, hi, x))
        for f in CONTINUOUS_FIELDS:
            continuous_out[f].append(_lerp(xs, continuous_vals[f], lo, hi, x))
        for f in DISCRETE_FIELDS:
            # step/hold: the last real value at or before x - never interpolated
            discrete_out[f].append(getattr(usable[lo], f))

    return ResampledSeries(grid_x=grid_x, confidence=conf_out, elapsed_s=elapsed_out,
                            continuous=continuous_out, discrete=discrete_out)


def _lerp(xs: list[float], ys: list, lo: int, hi: int, x: float) -> float | None:
    if lo == hi:
        return ys[lo]
    y0, y1 = ys[lo], ys[hi]
    if y0 is None or y1 is None:
        return None  # never fabricate a value across a gap in the source data
    x0, x1 = xs[lo], xs[hi]
    if x1 == x0:
        return y0
    frac = (x - x0) / (x1 - x0)
    return y0 + frac * (y1 - y0)


@dataclass
class SynchronizedComparison:
    session_id: str
    lap_number_a: int
    lap_number_b: int
    driver_a: int
    driver_b: int
    grid_x: list[float]
    series_a: ResampledSeries
    series_b: ResampledSeries
    confidence: list[Confidence]  # per grid point: min of both drivers' confidence


def synchronize_drivers(
    trace_a: LapDistanceTrace, trace_b: LapDistanceTrace, step: float = 0.001,
) -> SynchronizedComparison:
    """Align two drivers' laps onto the same normalized-distance grid.

    Both traces must already be normalized (see normalize_lap) - distance
    only means the same thing for both drivers once each has been divided
    by its own lap length. Requires both traces to share a session_id:
    comparing across different sessions/circuits on a shared [0, 1] axis
    would silently produce a comparison that looks valid but compares two
    different tracks' geometry.
    """
    if trace_a.session_id != trace_b.session_id:
        raise ValueError(
            f"cannot synchronize traces from different sessions "
            f"({trace_a.session_id!r} vs {trace_b.session_id!r}) - "
            f"normalized distance is only comparable within the same session/circuit"
        )
    series_a = resample_common_grid(trace_a, step)
    series_b = resample_common_grid(trace_b, step)
    combined_conf = [min((ca, cb), key=_confidence_rank)
                      for ca, cb in zip(series_a.confidence, series_b.confidence)]
    return SynchronizedComparison(
        session_id=trace_a.session_id, lap_number_a=trace_a.lap_number,
        lap_number_b=trace_b.lap_number, driver_a=trace_a.driver_number,
        driver_b=trace_b.driver_number, grid_x=series_a.grid_x,
        series_a=series_a, series_b=series_b, confidence=combined_conf,
    )


def delta_t(sync: SynchronizedComparison, x: float) -> float | None:
    """Elapsed-lap-time delta between driver A and driver B at normalized
    distance x: how much further into their own lap driver A was when they
    reached x, compared to driver B, evaluated at the SAME point on track -
    not a wall-clock timestamp difference (Phase 9's explicit distinction:
    the two drivers' laps started at different real-world instants).

    Positive means A has taken longer to reach x than B (A is behind at
    this point on track); negative means A is ahead.
    """
    try:
        idx = sync.grid_x.index(round(x, 10))
    except ValueError:
        return None
    ea, eb = sync.series_a.elapsed_s[idx], sync.series_b.elapsed_s[idx]
    if ea is None or eb is None:
        return None
    return ea - eb
