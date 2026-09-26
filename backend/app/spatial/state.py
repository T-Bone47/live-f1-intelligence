"""Phase 12A: where each car is at session time t, and one driver's trace.

State at t comes only from the driver's OWN two samples bracketing t:
- outside the driver's coverage: NO_COVERAGE (nothing, never extrapolated);
- bracket wider than MAX_GAP_S: STALE - the last sample with its age, never
  interpolated across the gap;
- both samples on the reference: the lap fraction is interpolated (unwrapped
  across the finish line) and the position is that point ON the reference;
- otherwise (pit lane, off the line, withheld fraction): x/y linear between
  the two observations, no fraction.
The spatial layer never infers session state; race phase is the timeline's.
"""

from __future__ import annotations

import bisect
import math
from array import array
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.analysis.common.models import Confidence
from app.analysis.lap_distance import MAX_GAP_S, confidence_rank
from app.analysis.track_geometry import Centerline
from app.spatial.reference import SPATIAL_SEARCH_WINDOW
from app.spatial.samples import ClassifiedSample, SampleFlag

FLAG_CODES = {SampleFlag.ON_REFERENCE: 0, SampleFlag.PIT_LANE: 1, SampleFlag.OFF_REFERENCE: 2}
CONF_CODES = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1, Confidence.NONE: 0}
_FLAGS = {v: k for k, v in FLAG_CODES.items()}
_CONFS = {v: k for k, v in CONF_CODES.items()}
_SEVERITY = {SampleFlag.ON_REFERENCE: 0, SampleFlag.OFF_REFERENCE: 1, SampleFlag.PIT_LANE: 2}


@dataclass
class DriverTrack:
    """One driver's classified samples as parallel, time-sorted arrays."""
    t: array
    x: array
    y: array
    fraction: array   # NaN = no fraction
    flag: array
    confidence: array
    lap: array        # -1 = no lap


def empty_track() -> DriverTrack:
    return DriverTrack(array("d"), array("d"), array("d"), array("d"),
                       array("b"), array("b"), array("h"))


def track_from_samples(samples: Sequence[ClassifiedSample]) -> DriverTrack:
    return DriverTrack(
        t=array("d", [s.t for s in samples]), x=array("d", [s.x for s in samples]),
        y=array("d", [s.y for s in samples]),
        fraction=array("d", [math.nan if s.fraction is None else s.fraction for s in samples]),
        flag=array("b", [FLAG_CODES[s.flag] for s in samples]),
        confidence=array("b", [CONF_CODES[s.confidence] for s in samples]),
        lap=array("h", [-1 if s.lap is None else s.lap for s in samples]))


@dataclass
class SpatialIndex:
    session_id: str
    track_id: str
    ref_points: tuple[tuple[float, float], ...]
    finish_fraction: float
    lap_length_m: float | None
    tracks: dict[int, DriverTrack]
    centerline: Centerline = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.centerline = Centerline(list(self.ref_points), SPATIAL_SEARCH_WINDOW)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


def _metres(index: SpatialIndex, fraction: float | None) -> float | None:
    if fraction is None or index.lap_length_m is None:
        return None
    return fraction * index.lap_length_m


def _no_coverage(driver: int) -> dict:
    return {"driver_number": driver, "status": "NO_COVERAGE", "flag": None, "confidence": None,
            "x": None, "y": None, "reference_fraction": None, "distance_m": None,
            "lap_number": None, "bracket": None, "age_s": None}


def _sample(index: SpatialIndex, trk: DriverTrack, i: int) -> dict:
    frac = None if math.isnan(trk.fraction[i]) else trk.fraction[i]
    return {"x": trk.x[i], "y": trk.y[i], "flag": _FLAGS[trk.flag[i]].value,
            "reference_fraction": frac, "distance_m": _metres(index, frac),
            "lap_number": None if trk.lap[i] < 0 else trk.lap[i],
            "confidence": _CONFS[trk.confidence[i]].value}


def _entry(index: SpatialIndex, driver: int, trk: DriverTrack, t: float) -> dict:
    if not trk.t or t < trk.t[0] or t > trk.t[-1]:
        return _no_coverage(driver)
    hi = bisect.bisect_left(trk.t, t)
    lo = hi if trk.t[hi] == t else hi - 1
    gap = trk.t[hi] - trk.t[lo]
    bracket = {"before": iso(trk.t[lo]), "after": iso(trk.t[hi]), "gap_s": gap}
    if gap > MAX_GAP_S:
        return {"driver_number": driver, "status": "STALE", **_sample(index, trk, lo),
                "confidence": Confidence.LOW.value, "bracket": bracket, "age_s": t - trk.t[lo]}
    a = 0.0 if gap == 0 else (t - trk.t[lo]) / gap
    flag_a, flag_b = _FLAGS[trk.flag[lo]], _FLAGS[trk.flag[hi]]
    conf = min((_CONFS[trk.confidence[lo]], _CONFS[trk.confidence[hi]]), key=confidence_rank)
    fa, fb, la, lb = trk.fraction[lo], trk.fraction[hi], trk.lap[lo], trk.lap[hi]
    laps_ok = la == lb or (la >= 0 and lb == la + 1)
    if (flag_a is SampleFlag.ON_REFERENCE and flag_b is SampleFlag.ON_REFERENCE
            and not math.isnan(fa) and not math.isnan(fb) and laps_ok):
        if fb < fa - 0.5:                      # the car crossed the finish line
            fb += 1.0
        f = fa + a * (fb - fa)
        lap = la if f < 1.0 else lb
        f %= 1.0
        x, y = index.centerline.point_at(
            ((f + index.finish_fraction) % 1.0) * index.centerline.total_length)
        return {"driver_number": driver, "status": "POSITIONED", "flag": SampleFlag.ON_REFERENCE.value,
                "confidence": conf.value, "x": x, "y": y, "reference_fraction": f,
                "distance_m": _metres(index, f), "lap_number": None if lap < 0 else lap,
                "bracket": bracket, "age_s": None}
    flag = max((flag_a, flag_b), key=_SEVERITY.__getitem__)
    return {"driver_number": driver, "status": "POSITIONED", "flag": flag.value,
            "confidence": conf.value,
            "x": trk.x[lo] + a * (trk.x[hi] - trk.x[lo]), "y": trk.y[lo] + a * (trk.y[hi] - trk.y[lo]),
            "reference_fraction": None, "distance_m": None, "lap_number": None,
            "bracket": bracket, "age_s": None}


def state_at(index: SpatialIndex, t: float) -> list[dict]:
    """One entry per driver of the session, sorted by driver number."""
    return [_entry(index, d, index.tracks[d], t) for d in sorted(index.tracks)]


def trace(index: SpatialIndex, driver: int, t0: float, t1: float) -> list[dict]:
    """The driver's classified samples in [t0, t1], time order. KeyError for
    a driver the session has no track for."""
    trk = index.tracks[driver]
    lo, hi = bisect.bisect_left(trk.t, t0), bisect.bisect_right(trk.t, t1)
    return [{"ts": iso(trk.t[i]), **_sample(index, trk, i)} for i in range(lo, hi)]
