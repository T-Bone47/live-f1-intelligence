"""Phase 12A: every location sample classified against the reference.

- PIT_LANE: inside a pit window whose semantics were verified on the data.
- OFF_REFERENCE: further from the reference line than the derived tolerance
  (garage, red-flag pit lane queue, off track).
- ON_REFERENCE: on the line. Only these get a lap fraction (measured from the
  measured finish line), and inside a timed lap the Phase 10.3 continuity
  guards decide their confidence - a jump is withheld (NONE), never repaired.

Off-line samples keep their observed x/y (confidence HIGH: the coordinates
are observations) but never get a fraction: pit-lane travel is not forced
onto the racing reference.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from app.analysis.common.models import Confidence
from app.analysis.track_geometry import project_positions
from app.core.models import TelemetryLocationSample
from app.spatial.reference import Reference
from app.spatial.source import LapRow, Sample, SpatialInputs
from app.spatial.timing_lines import nearest_rank

PIT_WINDOW_MIN_SHARE = 0.90
TOL_QUANTILE = 0.999
PIT_INSIDE_MAX_SHARE = 0.001

Window = tuple[int, float, float]  # (driver, t0, t1)


class SampleFlag(str, Enum):
    ON_REFERENCE = "ON_REFERENCE"
    PIT_LANE = "PIT_LANE"
    OFF_REFERENCE = "OFF_REFERENCE"


@dataclass(frozen=True)
class PitWindowResult:
    mode: Literal["ENTRY", "EXIT", "NONE"]
    share_entry: float | None
    share_exit: float | None
    samples_entry: int
    samples_exit: int


@dataclass(frozen=True)
class ClassifiedSample:
    t: float
    x: float
    y: float
    flag: SampleFlag
    fraction: float | None  # lap fraction from the finish line, [0, 1)
    lap: int | None
    confidence: Confidence


def _in_range(samples: Sequence[Sample], t0: float, t1: float) -> Sequence[Sample]:
    ts = [s[0] for s in samples]
    return samples[bisect.bisect_left(ts, t0):bisect.bisect_right(ts, t1)]


def _offsets(ref: Reference, samples: Sequence[Sample]) -> list[float]:
    out, hint = [], None
    for _t, x, y in samples:
        p = ref.centerline.project(x, y, hint)
        hint = p.segment
        out.append(p.offset)
    return out


def lateral_offsets(inputs: SpatialInputs, ref: Reference, laps: Sequence[LapRow]) -> list[float]:
    """Lateral offsets (feed units) of every sample inside the given laps."""
    out: list[float] = []
    for r in laps:
        end = r.start + (r.duration or 0.0)
        out += _offsets(ref, _in_range(inputs.samples.get(r.driver, ()), r.start, end))
    return out


def derive_tolerance(inputs: SpatialInputs, ref: Reference,
                     green: Sequence[LapRow]) -> tuple[float, dict[str, float], int]:
    """ON_REFERENCE tolerance = p99.9 of lateral offsets on eligible laps."""
    offs = lateral_offsets(inputs, ref, green)
    pct = {k: nearest_rank(offs, q)
           for k, q in (("p50", 0.5), ("p90", 0.9), ("p99", 0.99), ("p999", TOL_QUANTILE))}
    return pct["p999"], pct, len(offs)


def pit_windows(inputs: SpatialInputs, mode: Literal["ENTRY", "EXIT"]) -> list[Window]:
    """ENTRY: [ts, ts + lane]; EXIT: [ts - lane, ts]. Stops without a lane
    duration give no window."""
    out = []
    for d in sorted(inputs.pits):
        for p in inputs.pits[d]:
            if p.lane_s is None:
                continue
            out.append((d, p.ts, p.ts + p.lane_s) if mode == "ENTRY" else (d, p.ts - p.lane_s, p.ts))
    return out


def _window_offsets(inputs: SpatialInputs, ref: Reference, windows: Sequence[Window]) -> list[float]:
    out: list[float] = []
    for d, t0, t1 in windows:
        out += _offsets(ref, _in_range(inputs.samples.get(d, ()), t0, t1))
    return out


def inside_share(inputs: SpatialInputs, ref: Reference, tol: float,
                 windows: Sequence[Window]) -> tuple[float | None, int]:
    """Share of pit-window samples that the tolerance would call on-line."""
    offs = _window_offsets(inputs, ref, windows)
    return (sum(o <= tol for o in offs) / len(offs) if offs else None), len(offs)


def choose_pit_mode(inputs: SpatialInputs, ref: Reference, tol: float) -> PitWindowResult:
    """Measure both window hypotheses; use the one whose samples are off the
    line most often, and only if at least PIT_WINDOW_MIN_SHARE are."""
    shares: dict[str, tuple[float | None, int]] = {}
    for mode in ("ENTRY", "EXIT"):
        offs = _window_offsets(inputs, ref, pit_windows(inputs, mode))  # type: ignore[arg-type]
        shares[mode] = ((sum(o > tol for o in offs) / len(offs)) if offs else None, len(offs))
    best = max(("ENTRY", "EXIT"), key=lambda m: (-1.0 if shares[m][0] is None else shares[m][0],
                                                 m == "EXIT"))
    share = shares[best][0]
    mode = best if share is not None and share >= PIT_WINDOW_MIN_SHARE else "NONE"
    return PitWindowResult(mode=mode, share_entry=shares["ENTRY"][0],  # type: ignore[arg-type]
                           share_exit=shares["EXIT"][0], samples_entry=shares["ENTRY"][1],
                           samples_exit=shares["EXIT"][1])


def classify_driver(inputs: SpatialInputs, driver: int, ref: Reference, finish_fraction: float,
                    tol: float, windows: Sequence[Window]) -> list[ClassifiedSample]:
    samples = inputs.samples.get(driver, ())
    mine = [(t0, t1) for d, t0, t1 in windows if d == driver]
    total = ref.centerline.total_length
    timed = sorted((r for r in inputs.laps.get(driver, ()) if r.duration is not None),
                   key=lambda r: r.start)
    starts = [r.start for r in timed]
    out: list[ClassifiedSample | None] = [None] * len(samples)
    in_lap: dict[int, list[int]] = {}
    hint = None
    for i, (t, x, y) in enumerate(samples):
        if any(t0 <= t <= t1 for t0, t1 in mine):
            out[i] = ClassifiedSample(t, x, y, SampleFlag.PIT_LANE, None, None, Confidence.HIGH)
            continue
        p = ref.centerline.project(x, y, hint)
        hint = p.segment
        if p.offset > tol:
            out[i] = ClassifiedSample(t, x, y, SampleFlag.OFF_REFERENCE, None, None, Confidence.HIGH)
            continue
        k = bisect.bisect_right(starts, t) - 1
        if k >= 0 and t <= timed[k].start + (timed[k].duration or 0.0):
            in_lap.setdefault(k, []).append(i)
        else:  # on the line but outside any timed lap: no continuity check, no lap
            out[i] = ClassifiedSample(t, x, y, SampleFlag.ON_REFERENCE,
                                      (p.s / total - finish_fraction) % 1.0, None, Confidence.LOW)
    for k, idx in in_lap.items():
        lap = timed[k]
        locs = [TelemetryLocationSample.model_construct(
                    session_id=inputs.session_id, driver_number=driver,
                    ts=datetime.fromtimestamp(samples[i][0], UTC), x=samples[i][1],
                    y=samples[i][2], z=None, provenance=None)
                for i in idx]
        projected = project_positions(ref.centerline, locs, lap.duration or 0.0)
        # project_positions unwraps from the reference start, which sits at the
        # line; measured from the finish line itself, a lap runs over [0, 1).
        # A position outside that (before the measured line at the lap's start,
        # past it at the end) contradicts the timing lap: the lap is withheld
        # rather than paired with a distance one lap away.
        finish_u = finish_fraction - 1.0 if finish_fraction > 0.5 else finish_fraction
        for i, pp in zip(idx, projected, strict=True):
            t, x, y = samples[i]
            if pp.confidence is Confidence.NONE:
                out[i] = ClassifiedSample(t, x, y, SampleFlag.ON_REFERENCE, None, lap.lap,
                                          pp.confidence)
                continue
            u = pp.fraction - finish_u
            out[i] = ClassifiedSample(t, x, y, SampleFlag.ON_REFERENCE, u % 1.0,
                                      lap.lap if 0.0 <= u < 1.0 else None, pp.confidence)
    return [s for s in out if s is not None]
