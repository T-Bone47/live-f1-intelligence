"""Phase 12A: the official timing lines, measured on the reference.

Every eligible lap gives three probes from official timing: its start (the
finish line), start + S1 (the S1 line) and start + S1 + S2 (the S2 line).
The car's position at each probe - interpolated between two real samples of
THAT driver, never across a gap - is projected onto the reference. A line's
location is the circular median of its crossings; how far crossings fall
from it is the measured error of placing a timed event on the track. Nothing
is trimmed: outliers stay in the statistics and are listed.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.analysis.lap_distance import MAX_GAP_S
from app.spatial.reference import Reference, pit_adjacent
from app.spatial.source import Sample, SpatialInputs

LINES = ("FINISH", "S1", "S2")
EXCLUSION_REASONS = ("LAP_1", "PIT_ADJACENT", "UNTIMED", "NO_SECTOR_TIME", "NO_BRACKET", "GAP")
_QUANTILES = (("median", 0.5), ("p90", 0.9), ("p95", 0.95), ("p99", 0.99))


def nearest_rank(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: sorted(values)[ceil(q*n) - 1]."""
    v = sorted(values)
    if not v:
        raise ValueError("nearest_rank of an empty sequence")
    return v[max(0, math.ceil(q * len(v)) - 1)]


def circular_diff(a: float, b: float) -> float:
    """a - b on the unit circle, in [-0.5, 0.5)."""
    return ((a - b + 0.5) % 1.0) - 0.5


def circular_median(fractions: Sequence[float]) -> float:
    """Median of lap fractions that may straddle 0/1: cut the circle at its
    largest gap, take the ordinary median there, map back to [0, 1)."""
    v = sorted(f % 1.0 for f in fractions)
    if not v:
        raise ValueError("circular_median of an empty sequence")
    n = len(v)
    gaps = [(v[i + 1] - v[i], i + 1) for i in range(n - 1)] + [(1.0 - v[-1] + v[0], 0)]
    start = max(gaps)[1]
    if n % 2:
        return v[(start + n // 2) % n]
    a, b = v[(start + n // 2 - 1) % n], v[(start + n // 2) % n]
    return (a + circular_diff(b, a) / 2) % 1.0


def position_at(samples: Sequence[Sample], t: float, max_gap_s: float = MAX_GAP_S,
                times: Sequence[float] | None = None) -> tuple[float, float] | None:
    """(x, y) at t, linear in time between the two bracketing samples; None
    outside the samples or across a gap wider than max_gap_s."""
    ts = times if times is not None else [s[0] for s in samples]
    if not ts or t < ts[0] or t > ts[-1]:
        return None
    hi = bisect.bisect_left(ts, t)
    if ts[hi] == t:
        return samples[hi][1], samples[hi][2]
    (t0, x0, y0), (t1, x1, y1) = samples[hi - 1], samples[hi]
    if t1 - t0 > max_gap_s:
        return None
    a = (t - t0) / (t1 - t0)
    return x0 + a * (x1 - x0), y0 + a * (y1 - y0)


@dataclass(frozen=True)
class LineMeasurement:
    line: str
    fraction: float                      # of the reference loop, from its start
    x: float
    y: float
    n: int
    exclusions: dict[str, int]
    dispersion_fraction: dict[str, float]
    dispersion_m: dict[str, float] | None
    worst: tuple[tuple[int, int, float], ...]


def _probes(start: float, s1: float | None, s2: float | None) -> dict[str, float | None]:
    return {"FINISH": start,
            "S1": None if s1 is None else start + s1,
            "S2": None if s1 is None or s2 is None else start + s1 + s2}


def measure_lines(inputs: SpatialInputs, ref: Reference,
                  lap_length_m: float | None) -> dict[str, LineMeasurement]:
    """Each line with at least one crossing (a line without any is absent)."""
    touched = pit_adjacent(inputs)
    total = ref.centerline.total_length
    excl = {line: dict.fromkeys(EXCLUSION_REASONS, 0) for line in LINES}
    cross: dict[str, list[tuple[float, int, int]]] = {line: [] for line in LINES}
    times = {d: [s[0] for s in ss] for d, ss in inputs.samples.items()}
    for d in sorted(inputs.laps):
        samples, ts = inputs.samples.get(d, ()), times.get(d, [])
        for r in inputs.laps[d]:
            reason = ("LAP_1" if r.lap < 2 else
                      "PIT_ADJACENT" if r.pit_out or (d, r.lap) in touched else
                      "UNTIMED" if r.duration is None else None)
            if reason:
                for line in LINES:
                    excl[line][reason] += 1
                continue
            for line, t in _probes(r.start, r.s1, r.s2).items():
                if t is None:
                    excl[line]["NO_SECTOR_TIME"] += 1
                elif not ts or t < ts[0] or t > ts[-1]:
                    excl[line]["NO_BRACKET"] += 1
                elif (p := position_at(samples, t, times=ts)) is None:
                    excl[line]["GAP"] += 1
                else:
                    cross[line].append((ref.centerline.project(*p).s / total, d, r.lap))

    out: dict[str, LineMeasurement] = {}
    for line in LINES:
        cs = cross[line]
        if not cs:
            continue
        frac = circular_median([c[0] for c in cs])
        devs = [(abs(circular_diff(c[0], frac)), c[1], c[2]) for c in cs]
        dv = [dev[0] for dev in devs]
        disp = {k: nearest_rank(dv, q) for k, q in _QUANTILES} | {"max": max(dv)}
        scale = lap_length_m if lap_length_m is not None else 1.0
        worst = tuple((drv, lap, dev * scale)
                      for dev, drv, lap in sorted(devs, key=lambda z: (-z[0], z[1], z[2]))[:5])
        x, y = ref.centerline.point_at(frac * total)
        out[line] = LineMeasurement(
            line=line, fraction=frac, x=x, y=y, n=len(cs), exclusions=excl[line],
            dispersion_fraction=disp,
            dispersion_m=None if lap_length_m is None else {k: v * lap_length_m
                                                            for k, v in disp.items()},
            worst=worst)
    return out


def inter_line_fractions(lines: Mapping[str, LineMeasurement]) -> tuple[float, float, float]:
    """FINISH->S1, S1->S2, S2->FINISH as fractions of the loop."""
    f, s1, s2 = (lines[name].fraction for name in LINES)
    return (s1 - f) % 1.0, (s2 - s1) % 1.0, (f - s2) % 1.0


def reference_independence_m(inputs: SpatialInputs, refs: Sequence[Reference],
                             lap_length_m: float | None) -> float | None:
    """Largest spread, across reference laps, of any inter-line distance.
    None without a cited length or with fewer than two references."""
    if lap_length_m is None or len(refs) < 2:
        return None
    spacings = []
    for ref in refs:
        lines = measure_lines(inputs, ref, lap_length_m)
        if set(lines) != set(LINES):
            return None
        spacings.append(inter_line_fractions(lines))
    return max(max(col) - min(col) for col in zip(*spacings, strict=True)) * lap_length_m
