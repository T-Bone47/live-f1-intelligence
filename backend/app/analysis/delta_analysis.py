"""Phase 10.2: deterministic engineering delta analysis.

Consumes a Phase 10.1C DriverLapComparison (itself built on the 10.1B
lap-distance engine) and turns the synchronized telemetry into:

1. a per-distance-point delta model (DeltaSample) - both drivers' values,
   delta_t, and telemetry differences, with categorical fields compared
   for equality, never subtracted;
2. a delta-curve summary - delta at start/finish, maximum gain and
   maximum loss with the distance each occurs at;
3. deterministic gain/loss segmentation of the delta curve.

No second synchronization: everything reads the grid that
app.analysis.lap_distance.synchronize_drivers already produced. No new
confidence system: segment/overall confidence is the existing
Confidence, rolled up with the existing confidence_rank.

Sign convention - inherited from 10.1B's delta_t, verified in its source,
not redefined here:

    delta_t(x) = elapsed_A(x) - elapsed_B(x)
    negative -> A reached x sooner (A ahead); positive -> A behind.

So a DECREASING delta_t means A is gaining time; increasing means losing.

Out of scope (Phase 10.2's own boundary): corners, braking-point
attribution, track geometry, natural-language explanation. Segments are
regions of normalized distance, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.analysis.common.models import Confidence
from app.analysis.lap_comparison import DriverLapComparison
from app.analysis.lap_distance import CONTINUOUS_FIELDS, DISCRETE_FIELDS, confidence_rank

SIGN_CONVENTION = "delta_t = elapsed_A - elapsed_B; negative means A is ahead"

# Default minimum time change for a region to count as GAINING/LOSING
# rather than STABLE. Evidence: official F1 timing - and OpenF1's /laps
# data used in this project's tests (e.g. lap_duration 91.743) - resolves
# time to the thousandth of a second. A delta change smaller than that is
# below the resolution of the sport's own timing and is not reported as a
# gain or loss. This is a resolution floor, NOT a telemetry-noise model:
# calibrating a noise-aware threshold needs real pairs of complete
# two-driver laps, which this repository does not contain yet. Callers can
# raise it via min_segment_change_s.
TIMING_RESOLUTION_S = 0.001


class SegmentKind(str, Enum):
    GAINING = "GAINING"        # delta_t decreasing: A taking time out of B
    LOSING = "LOSING"          # delta_t increasing: A giving time to B
    RECOVERING = "RECOVERING"  # GAINING while A was behind at the region's start
    STABLE = "STABLE"          # net change below min_segment_change_s
    NO_DATA = "NO_DATA"        # at least one driver has no telemetry coverage here


@dataclass(frozen=True)
class DeltaSample:
    """Both drivers at one normalized-distance grid point.

    continuous_delta[f] = value_A - value_B for speed/throttle/brake/rpm
    (None if either side is missing). Discrete fields (gear, drs) are never
    subtracted - discrete_differs[f] is a plain equality check, None if
    either side is missing.
    """

    x: float
    delta_t_s: float | None
    elapsed_a_s: float | None = None
    elapsed_b_s: float | None = None
    a: dict = field(default_factory=dict)
    b: dict = field(default_factory=dict)
    continuous_delta: dict = field(default_factory=dict)
    discrete_differs: dict = field(default_factory=dict)
    confidence: Confidence = Confidence.NONE


@dataclass(frozen=True)
class DeltaSegment:
    """A contiguous region of the delta curve with one behavior.

    Bounded by grid indices [start_index, end_index] (inclusive, shared
    with the neighbouring segment). time_change_s = delta_end - delta_start:
    negative means A gained time across this region.
    """

    kind: SegmentKind
    start_index: int
    end_index: int
    x_start: float
    x_end: float
    delta_start_s: float | None
    delta_end_s: float | None
    time_change_s: float | None
    mean_continuous_delta: dict
    discrete_difference_fraction: dict
    confidence: Confidence


@dataclass
class DeltaAnalysis:
    comparison: DriverLapComparison
    samples: list[DeltaSample]
    segments: list[DeltaSegment]
    delta_at_start_s: float | None
    delta_at_finish_s: float | None
    max_gain_s: float | None   # most negative delta_t (A's largest lead); None if A never led
    max_gain_x: float | None
    max_loss_s: float | None   # most positive delta_t (A's largest deficit); None if A never trailed
    max_loss_x: float | None
    confidence: Confidence
    sign_convention: str = SIGN_CONVENTION


def build_delta_samples(comparison: DriverLapComparison) -> list[DeltaSample]:
    """One DeltaSample per grid point of the existing synchronized grid."""
    sync = comparison.sync
    sa, sb = sync.series_a, sync.series_b
    out: list[DeltaSample] = []
    for i, x in enumerate(sync.grid_x):
        ea, eb = sa.elapsed_s[i], sb.elapsed_s[i]
        a_vals = {f: sa.continuous[f][i] for f in CONTINUOUS_FIELDS}
        a_vals.update({f: sa.discrete[f][i] for f in DISCRETE_FIELDS})
        b_vals = {f: sb.continuous[f][i] for f in CONTINUOUS_FIELDS}
        b_vals.update({f: sb.discrete[f][i] for f in DISCRETE_FIELDS})
        cont = {f: (a_vals[f] - b_vals[f]
                    if a_vals[f] is not None and b_vals[f] is not None else None)
                for f in CONTINUOUS_FIELDS}
        disc = {f: (a_vals[f] != b_vals[f]
                    if a_vals[f] is not None and b_vals[f] is not None else None)
                for f in DISCRETE_FIELDS}
        out.append(DeltaSample(
            x=x, delta_t_s=(ea - eb if ea is not None and eb is not None else None),
            elapsed_a_s=ea, elapsed_b_s=eb, a=a_vals, b=b_vals,
            continuous_delta=cont, discrete_differs=disc,
            confidence=sync.confidence[i],
        ))
    return out


def _step_kind(d0: float | None, d1: float | None) -> SegmentKind:
    if d0 is None or d1 is None:
        return SegmentKind.NO_DATA
    dd = d1 - d0
    if dd < 0:
        return SegmentKind.GAINING
    if dd > 0:
        return SegmentKind.LOSING
    return SegmentKind.STABLE


def segment_delta_curve(
    samples: list[DeltaSample], min_segment_change_s: float = TIMING_RESOLUTION_S,
) -> list[DeltaSegment]:
    """Deterministic segmentation of the delta curve, O(n) in grid points.

    1. Label each step between consecutive grid points by the sign of the
       delta change (GAINING / LOSING / STABLE), or NO_DATA if either end
       lacks coverage - a coverage gap is shown as a region, never bridged.
    2. Merge consecutive steps with the same label.
    3. Relabel any GAINING/LOSING run whose net change is below
       min_segment_change_s as STABLE (sub-resolution wiggle is not a gain
       or loss), then merge adjacent same-label runs again.
    4. A GAINING segment that starts with A behind (delta_start > 0) is
       labelled RECOVERING.
    """
    if len(samples) < 2:
        return []

    runs: list[list] = []  # [kind, lo, hi]
    for i in range(1, len(samples)):
        k = _step_kind(samples[i - 1].delta_t_s, samples[i].delta_t_s)
        if runs and runs[-1][0] == k:
            runs[-1][2] = i
        else:
            runs.append([k, i - 1, i])

    for r in runs:
        if r[0] in (SegmentKind.GAINING, SegmentKind.LOSING):
            change = samples[r[2]].delta_t_s - samples[r[1]].delta_t_s
            if abs(change) < min_segment_change_s:
                r[0] = SegmentKind.STABLE

    merged: list[list] = []
    for r in runs:
        if merged and merged[-1][0] == r[0]:
            merged[-1][2] = r[2]
        else:
            merged.append(list(r))

    return [_build_segment(samples, kind, lo, hi) for kind, lo, hi in merged]


def _build_segment(samples: list[DeltaSample], kind: SegmentKind,
                    lo: int, hi: int) -> DeltaSegment:
    d0, d1 = samples[lo].delta_t_s, samples[hi].delta_t_s
    if kind is SegmentKind.GAINING and d0 is not None and d0 > 0:
        kind = SegmentKind.RECOVERING
    region = samples[lo:hi + 1]

    mean_cont: dict = {}
    for f in CONTINUOUS_FIELDS:
        vals = [s.continuous_delta[f] for s in region if s.continuous_delta.get(f) is not None]
        mean_cont[f] = sum(vals) / len(vals) if vals else None
    disc_frac: dict = {}
    for f in DISCRETE_FIELDS:
        vals = [s.discrete_differs[f] for s in region if s.discrete_differs.get(f) is not None]
        disc_frac[f] = sum(vals) / len(vals) if vals else None

    return DeltaSegment(
        kind=kind, start_index=lo, end_index=hi,
        x_start=samples[lo].x, x_end=samples[hi].x,
        delta_start_s=d0, delta_end_s=d1,
        time_change_s=(d1 - d0 if d0 is not None and d1 is not None else None),
        mean_continuous_delta=mean_cont, discrete_difference_fraction=disc_frac,
        confidence=(Confidence.NONE if kind is SegmentKind.NO_DATA
                    else min((s.confidence for s in region), key=confidence_rank)),
    )


def analyze_delta(
    comparison: DriverLapComparison, min_segment_change_s: float = TIMING_RESOLUTION_S,
) -> DeltaAnalysis:
    """Full engineering delta analysis of one 10.1C comparison.

    Delta at an arbitrary distance is deliberately not re-implemented here -
    use app.analysis.lap_comparison.delta_at(analysis.comparison, x).
    """
    samples = build_delta_samples(comparison)
    segments = segment_delta_curve(samples, min_segment_change_s)

    max_gain_s = max_gain_x = max_loss_s = max_loss_x = None
    for s in samples:  # strict comparisons -> first occurrence wins on ties
        d = s.delta_t_s
        if d is None:
            continue
        if d < 0 and (max_gain_s is None or d < max_gain_s):
            max_gain_s, max_gain_x = d, s.x
        if d > 0 and (max_loss_s is None or d > max_loss_s):
            max_loss_s, max_loss_x = d, s.x

    return DeltaAnalysis(
        comparison=comparison, samples=samples, segments=segments,
        delta_at_start_s=comparison.delta_at_start,
        delta_at_finish_s=comparison.delta_at_finish,
        max_gain_s=max_gain_s, max_gain_x=max_gain_x,
        max_loss_s=max_loss_s, max_loss_x=max_loss_x,
        confidence=comparison.confidence,
    )
