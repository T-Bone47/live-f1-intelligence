"""Phase 10.3: position-based lap alignment on a self-referential centerline.

Implements the approach already specified in
docs/PHASE_10_LAP_SYNCHRONIZATION.md ("Track coordinate model"):

- the reference path is the session's OWN reference lap (x, y) - every car
  in the session shares that coordinate frame, so there is zero cross-source
  alignment risk and no external geometry is involved;
- every other sample is placed on it by nearest-point-on-polyline
  projection -> arc length along the shared path;
- continuity checks reject impossible positions instead of smoothing them.

Why it matters (measured, docs/PHASE_10_2_REAL_DATA_VALIDATION.md): speed-
integrated distance drifted 2-4 m between two real drivers at the same
physical sector lines. In a 78 kph corner that is ~0.2 s of fake delta.
Position does not drift that way: both cars are measured against one path.

Unit-free by construction. OpenF1 states its x/y origin is arbitrary and does
not state the unit, so everything here works in FRACTIONS of the reference
path. The output is the existing LapDistanceTrace with
distance_m = fraction x lap_length_m, so normalize_lap / synchronize_drivers
/ delta_t / analyze_delta are reused unchanged - this module changes where
distance comes from, not how laps are compared.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from itertools import pairwise

from app.analysis.common.models import Confidence, LapClass
from app.analysis.lap_distance import (
    MAX_GAP_S,
    DistancePoint,
    LapDistanceTrace,
    _extra_fields,
    _provenance,
    confidence_rank,
    rollup_trace_confidence,
)
from app.core.models import Lap, TelemetryCarSample, TelemetryLocationSample

# Backward jitter smaller than this fraction of the path (~10 m on a 5 km
# lap) is treated as position noise: held at the previous value (distance
# never runs backwards) and marked MEDIUM. Larger backward jumps are
# outliers. Provisional: scripts/audit_real_pair.py reports how often real
# data triggers it, so it can be calibrated on evidence.
BACKTRACK_TOL_FRACTION = 0.002

# A sample implying progress faster than this multiple of the lap's own mean
# rate is physically impossible. Evidence: on the real Singapore pair, top
# speed / lap-average speed = 315 / ~195 kph ~ 1.6, so 3x leaves wide margin.
MAX_RATE_FACTOR = 3.0

# Lateral distance from the reference path beyond this fraction of its
# length (~50 m on 5 km) means the point is not on this path at all. A coarse
# sanity guard, NOT pit detection - pit laps are capped via LapClass.
OFFSET_TOL_FRACTION = 0.01

# Segments searched either side of the previous match before falling back to
# a full search. Consecutive samples move ~1 segment on real data.
SEARCH_WINDOW = 40


@dataclass(frozen=True)
class Projection:
    s: float          # arc length along the centerline, in the path's native units
    offset: float     # perpendicular distance from the path, native units
    segment: int      # index of the matched segment (use as the next hint)


@dataclass(frozen=True)
class ProjectedPosition:
    ts: object        # datetime
    fraction: float   # s / total_length, unwrapped (may be < 0 just before the line)
    offset: float
    confidence: Confidence


class Centerline:
    """An open polyline in the session's own (x, y) frame, start line -> finish line."""

    def __init__(self, points: list[tuple[float, float]]):
        self.points = points
        self.cum = [0.0]
        for (x0, y0), (x1, y1) in pairwise(points):
            self.cum.append(self.cum[-1] + math.hypot(x1 - x0, y1 - y0))
        self.total_length = self.cum[-1]

    def _on_segment(self, i: int, x: float, y: float) -> tuple[float, float]:
        (x0, y0), (x1, y1) = self.points[i], self.points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / seg2))
        px, py = x0 + t * dx, y0 + t * dy
        return math.hypot(x - px, y - py), self.cum[i] + t * (self.cum[i + 1] - self.cum[i])

    def _search(self, x: float, y: float, segments) -> Projection:
        best = None
        for i in segments:
            d, s = self._on_segment(i, x, y)
            if best is None or d < best[0]:   # strict: ties resolve to the first candidate
                best = (d, s, i)
        return Projection(s=best[1], offset=best[0], segment=best[2])

    def project(self, x: float, y: float, hint: int | None = None) -> Projection:
        """Nearest point on the polyline. With a hint (previous segment),
        search a window around it first. The window wraps modulo the segment
        count, because a lap path ends where it starts: a car crossing the
        line moves from the last segments to the first ones. If the best
        match lands on the window's edge the car may have moved further, so
        fall back to a full search."""
        n = len(self.points) - 1
        if hint is None or n <= 2 * SEARCH_WINDOW + 1:
            return self._search(x, y, range(n))
        window = [(hint + k) % n for k in range(-SEARCH_WINDOW, SEARCH_WINDOW + 1)]
        p = self._search(x, y, window)
        if p.segment in (window[0], window[-1]):
            return self._search(x, y, range(n))
        return p


def build_centerline(reference: list[TelemetryLocationSample]) -> Centerline:
    """Centerline from a reference lap's own location samples, in time order.
    Samples without x/y are dropped; consecutive repeats (a stationary or
    not-yet-updated position) are collapsed. Needs 3+ distinct points."""
    pts: list[tuple[float, float]] = []
    for s in sorted(reference, key=lambda r: r.ts):
        if s.x is None or s.y is None:
            continue
        if not pts or (s.x, s.y) != pts[-1]:
            pts.append((s.x, s.y))
    if len(pts) < 3:
        raise ValueError(f"centerline needs at least 3 distinct points, got {len(pts)}")
    return Centerline(pts)


def project_positions(centerline: Centerline, samples: list[TelemetryLocationSample],
                      lap_duration_s: float) -> list[ProjectedPosition]:
    """Project samples (time order) to unwrapped path fractions, flagging
    anything physically inconsistent instead of repairing it.

    - Unwrapping: each fraction takes the whole-lap shift (-1, 0, +1) that
      keeps it closest to the previous one; the first sample, if in the
      second half of the path, is before the line and becomes negative.
    - Small backward jitter -> held at the previous fraction, MEDIUM.
    - Large backward jump, impossible forward rate, or a time regression
      -> NONE (reported, excluded from continuity tracking).
    - Lateral offset beyond OFFSET_TOL_FRACTION of the path -> at most LOW.
    """
    total = centerline.total_length
    max_rate = MAX_RATE_FACTOR / lap_duration_s
    out: list[ProjectedPosition] = []
    prev_f = prev_t = hint = None
    for s in sorted(samples, key=lambda r: r.ts):
        if s.x is None or s.y is None:
            continue
        p = centerline.project(s.x, s.y, hint)
        raw = p.s / total
        if prev_f is None:
            f = raw - 1.0 if raw > 0.5 else raw
        else:
            f = min((raw - 1.0, raw, raw + 1.0), key=lambda c: abs(c - prev_f))
        conf = Confidence.HIGH
        t = s.ts.timestamp()
        if prev_f is not None:
            dt, df = t - prev_t, f - prev_f
            if df < 0 and -df <= BACKTRACK_TOL_FRACTION:
                f, conf = prev_f, Confidence.MEDIUM
            elif (df < 0) or (dt <= 0 and df > 0) or (dt > 0 and df / dt > max_rate):
                conf = Confidence.NONE
        if p.offset > OFFSET_TOL_FRACTION * total and conf is not Confidence.NONE:
            conf = min((conf, Confidence.LOW), key=confidence_rank)
        out.append(ProjectedPosition(ts=s.ts, fraction=f, offset=p.offset, confidence=conf))
        if conf is not Confidence.NONE:
            prev_f, prev_t, hint = f, t, p.segment
    return out


def build_position_distance_trace(
    lap: Lap, car_samples: list[TelemetryCarSample],
    location_samples: list[TelemetryLocationSample], centerline: Centerline,
    lap_length_m: float, lap_class: LapClass | None = None,
) -> LapDistanceTrace:
    """A LapDistanceTrace whose distance comes from position, not speed.

    Each car sample inside the lap window gets the path fraction linearly
    interpolated in time between the two bracketing accepted location
    samples; distance_m = fraction x lap_length_m. Car samples outside the
    location coverage are excluded - never extrapolated. time_origin is the
    official lap start, because position distance is measured from the
    physical timing line (so a sample 0.3 s after the line sits ~20 m in,
    not at 0 - which removes the start-offset bias of speed integration).
    """
    is_pit_lap = lap_class in (LapClass.PIT_IN, LapClass.PIT_OUT, LapClass.IN_LAP)
    is_invalid = lap_class in (LapClass.INVALID, LapClass.OUTLIER)
    empty = LapDistanceTrace(session_id=lap.session_id, driver_number=lap.driver_number,
                             lap_number=lap.lap_number, lap_class=lap_class,
                             is_pit_lap=is_pit_lap, confidence=Confidence.NONE,
                             time_origin=lap.started_at,
                             provenance=_provenance(lap.session_id, Confidence.NONE))
    if lap.duration_s is None:
        return empty
    t_start = lap.started_at.timestamp()
    t_end = t_start + lap.duration_s
    in_lap = [s for s in location_samples if t_start <= s.ts.timestamp() <= t_end]
    usable = [p for p in project_positions(centerline, in_lap, lap.duration_s)
              if p.confidence is not Confidence.NONE]
    if len(usable) < 2:
        return empty

    uts = [p.ts.timestamp() for p in usable]
    points: list[DistancePoint] = []
    prev_ts = None
    for c in car_samples:
        t = c.ts.timestamp()
        if not (t_start <= t <= t_end) or t < uts[0] or t > uts[-1]:
            continue
        hi = min(bisect.bisect_left(uts, t), len(uts) - 1)
        lo = hi if uts[hi] == t else hi - 1
        a, b = usable[lo], usable[hi]
        frac = a.fraction if lo == hi else \
            a.fraction + (t - uts[lo]) / (uts[hi] - uts[lo]) * (b.fraction - a.fraction)
        conf = min((a.confidence, b.confidence), key=confidence_rank)
        if uts[hi] - uts[lo] > MAX_GAP_S:
            conf = min((conf, Confidence.LOW), key=confidence_rank)
        points.append(DistancePoint(
            ts=c.ts, distance_m=frac * lap_length_m, normalized_distance=None,
            speed_kph=c.speed_kph, confidence=conf,
            gap_s=None if prev_ts is None else t - prev_ts, **_extra_fields(c)))
        prev_ts = t

    is_complete = bool(points) and \
        points[0].ts.timestamp() - t_start <= MAX_GAP_S and \
        t_end - points[-1].ts.timestamp() <= MAX_GAP_S
    confidence = rollup_trace_confidence(points, is_invalid=is_invalid,
                                         is_pit_lap=is_pit_lap, is_complete=is_complete)
    return LapDistanceTrace(
        session_id=lap.session_id, driver_number=lap.driver_number, lap_number=lap.lap_number,
        points=points, total_distance_m=points[-1].distance_m if points else None,
        lap_class=lap_class, is_pit_lap=is_pit_lap, is_complete=is_complete,
        confidence=confidence, time_origin=lap.started_at,
        provenance=_provenance(lap.session_id, confidence),
    )
