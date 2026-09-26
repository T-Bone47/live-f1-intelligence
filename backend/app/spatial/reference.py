"""Phase 12A: the session's deterministic reference lap, closed into a loop.

The reference path is one real lap of the session's own location feed (the
Phase 10.3 self-referential centerline), closed so projection wraps at the
line. It is chosen by a fixed rule - never by hand - so a rebuild picks the
same lap: the fastest eligible lap with full location coverage, ties broken
by driver number, then lap number.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from itertools import pairwise

from app.analysis.lap_distance import MAX_GAP_S
from app.analysis.track_geometry import Centerline
from app.spatial.source import LapRow, SpatialInputs


class NoReferenceLap(ValueError):
    """No lap qualifies, or its window holds fewer than 3 distinct points."""


@dataclass(frozen=True)
class Reference:
    driver: int
    lap: int
    start: float
    duration: float
    points: tuple[tuple[float, float], ...]  # closed: points[0] == points[-1]
    centerline: Centerline


def pit_adjacent(inputs: SpatialInputs) -> frozenset[tuple[int, int]]:
    """(driver, lap) pairs a pit stop touches: the lap it is recorded on and
    the next one - they cross timing lines in the pit lane."""
    out: set[tuple[int, int]] = set()
    for d, stops in inputs.pits.items():
        for p in stops:
            if p.lap is not None:
                out |= {(d, p.lap), (d, p.lap + 1)}
    return frozenset(out)


def _window(inputs: SpatialInputs, lap: LapRow) -> list[tuple[float, float, float]]:
    samples = inputs.samples.get(lap.driver, ())
    ts = [s[0] for s in samples]
    end = lap.start + (lap.duration or 0.0)
    return list(samples[bisect.bisect_left(ts, lap.start):bisect.bisect_right(ts, end)])


def _covered(inputs: SpatialInputs, lap: LapRow) -> bool:
    w = _window(inputs, lap)
    if not w or lap.duration is None:
        return False
    end = lap.start + lap.duration
    return (w[0][0] <= lap.start + MAX_GAP_S and w[-1][0] >= end - MAX_GAP_S
            and all(b[0] - a[0] <= MAX_GAP_S for a, b in pairwise(w)))


def eligible_laps(inputs: SpatialInputs, *, require_coverage: bool) -> list[LapRow]:
    """Timed laps from lap 2 on that no pit stop touches (and, if asked,
    with location coverage over the whole lap)."""
    touched = pit_adjacent(inputs)
    out = []
    for d in sorted(inputs.laps):
        for r in inputs.laps[d]:
            if r.duration is None or r.lap < 2 or r.pit_out or (d, r.lap) in touched:
                continue
            if require_coverage and not _covered(inputs, r):
                continue
            out.append(r)
    return out


def reference_candidates(inputs: SpatialInputs, k: int = 3) -> list[LapRow]:
    """The k best reference laps: fastest first, ties by driver then lap."""
    laps = eligible_laps(inputs, require_coverage=True)
    return sorted(laps, key=lambda r: (r.duration, r.driver, r.lap))[:k]


def build_reference(inputs: SpatialInputs, lap: LapRow) -> Reference:
    pts: list[tuple[float, float]] = []
    for _t, x, y in _window(inputs, lap):
        if not pts or (x, y) != pts[-1]:
            pts.append((x, y))
    if len(set(pts)) < 3:
        raise NoReferenceLap(f"reference lap #{lap.driver} L{lap.lap} has "
                             f"{len(set(pts))} distinct points (needs 3)")
    # the lap may already end on its first point: close without a zero-length segment
    closed = tuple(pts) if pts[-1] == pts[0] else (*pts, pts[0])
    return Reference(driver=lap.driver, lap=lap.lap, start=lap.start,
                     duration=float(lap.duration or 0.0), points=closed,
                     centerline=Centerline(list(closed)))
