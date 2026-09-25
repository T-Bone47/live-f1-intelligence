"""Phase 10.4: deterministic time-loss attribution.

Consumes a Phase 10.2 DeltaAnalysis (itself 10.1C over 10.1B) and turns it
into evidence-backed segments: where time was accumulated or recovered, by
how much, how certain that is, and which control inputs differed around it.
No second synchronization, no second delta: every delta value is a 10.2
DeltaSample.delta_t_s on the 10.1B grid. No LLM anywhere.

Sign convention (10.1B/10.2, unchanged): delta_t = elapsed_A - elapsed_B;
negative = A ahead. accumulated_change_s = delta_end - delta_start:
positive = A lost time in the segment, negative = A gained.

Why segments run straight-to-straight
-------------------------------------
On the real Singapore pair, the two drivers' integrated distances place the
official sector lines 4.31 m (S1) and 2.04 m (S2) apart. A misalignment e
at a point where the speed is v shifts delta_t there by e/v - 12 ms/m at
300 kph but 46 ms/m at 78 kph. A generic swing detector on that curve found
paired swings of -0.186 s then +0.186 s inside one 78 kph corner: the
signature of misalignment, not driving. Time change is therefore measured
only between points where the alignment error is smallest - the peak-speed
point on the straight between consecutive braking zones - so every corner
sits INSIDE a segment and each segment is "straight to straight".

Significance (a documented model, not a magic threshold)
--------------------------------------------------------
For a segment from i to j (speeds v_i, v_j in m/s, length L_ij in metres):

    band = E * |1/v_j - 1/v_i| + (D + W) * max(1/v_i, 1/v_j) + 0.001 s

The error of a delta CHANGE is e_i*(1/v_j - 1/v_i) + (e_j - e_i)/v_j for
misalignments e_i, e_j at the two ends. Terms:
- E bounds |e| (measured per comparison at the official sector lines,
  measure_alignment).
- D bounds the systematic change of e inside one segment. D = E
  (PROVISIONAL): the real anchors move 2.27 m between S1 and S2 across many
  segments (< E = 4.31 m). A linear drift rate fitted to two anchors was
  REJECTED: on synthetic ground truth it under-predicted a within-segment
  change about 5x.
- W is the random walk of integrated distance caused by speed quantization,
  DERIVED not tuned: the feed carries integer kph (verified), so each
  sample's speed is off by up to 0.5 kph, uniformly; integrated over the
  segment's real sample intervals dt that is sigma = (0.5/3.6/sqrt(3)) *
  sqrt(sum dt^2) metres per driver, W = 3 * sqrt(sigma_A^2 + sigma_B^2)
  (3 sigma, the conventional 99.7% level). On synthetic ground truth this
  is what moved delta by 1.8 ms through an IDENTICAL corner.
- 0.001 s is 10.2's TIMING_RESOLUTION_S. A segment is significant when
|accumulated_change_s| > band. With only two anchors per lap, E is a lower
bound on the true misalignment: "not significant" is definite, "significant"
means "not explained by the MEASURED alignment error".

Signals (app.analysis.attribution_signals) are located between real samples.
A difference between A and B is "resolvable" only when it cannot be
produced by the sampling brackets plus the misalignment bound E. Every
association is TEMPORAL_ASSOCIATION; nothing here asserts causation.
"""

from __future__ import annotations

import bisect
import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.analysis.attribution_signals import (
    SPEED_QUANTUM_KPH,
    DriverSignals,
    Phase,
    Transition,
    detect_signals,
)
from app.analysis.common.models import Confidence
from app.analysis.contextpacks import _fact
from app.analysis.delta_analysis import (
    SIGN_CONVENTION,
    TIMING_RESOLUTION_S,
    DeltaAnalysis,
    DeltaSample,
    SegmentKind,
)
from app.analysis.lap_distance import LapDistanceTrace, confidence_rank
from app.core.models import Lap

# 1.1.0: structured limitations (code + message) and per-driver channel
# availability added to the report. No numeric change: every segment, band,
# sector and accounting value is identical to 1.0.0 (verified by diffing the
# regenerated real-pair evidence).
CALC_VERSION = "attribution-1.1.0"

# PROVISIONAL default, used only when a comparison has no official sector
# anchors of its own: measured on the ONE real pair in this repository
# (Singapore 2023 qualifying, #55 lap 19 vs #63 lap 16) - S1 line 4.308 m,
# S2 line 2.036 m apart.
DEFAULT_MISALIGNMENT_M = 4.31

ASSOCIATION = "TEMPORAL_ASSOCIATION"


class AlignmentMode(str, Enum):
    NORMALIZED_DISTANCE = "NORMALIZED_DISTANCE"   # 10.1B speed-integrated distance
    POSITION_PROJECTED = "POSITION_PROJECTED"     # 10.3 projection (not yet validated)
    CENTERLINE_CALIBRATED = "CENTERLINE_CALIBRATED"
    OTHER = "OTHER"


class LimitationCode(str, Enum):
    ALIGNMENT_NORMALIZED_DISTANCE = "ALIGNMENT_NORMALIZED_DISTANCE"
    ALIGNMENT_POSITION_PROJECTED_UNVALIDATED = "ALIGNMENT_POSITION_PROJECTED_UNVALIDATED"
    UNCERTAINTY_DEFAULT_PROVISIONAL = "UNCERTAINTY_DEFAULT_PROVISIONAL"
    UNCERTAINTY_SINGLE_ANCHOR = "UNCERTAINTY_SINGLE_ANCHOR"
    UNCERTAINTY_ANCHORS_LOWER_BOUND = "UNCERTAINTY_ANCHORS_LOWER_BOUND"
    UNCERTAINTY_WITHIN_SEGMENT_PROVISIONAL = "UNCERTAINTY_WITHIN_SEGMENT_PROVISIONAL"
    BRAKE_CHANNEL_MISSING = "BRAKE_CHANNEL_MISSING"
    THROTTLE_CHANNEL_MISSING = "THROTTLE_CHANNEL_MISSING"
    GEAR_CHANNEL_MISSING = "GEAR_CHANNEL_MISSING"
    DRS_CHANNEL_MISSING = "DRS_CHANNEL_MISSING"
    TELEMETRY_COVERAGE_INCOMPLETE = "TELEMETRY_COVERAGE_INCOMPLETE"
    INTRA_SEGMENT_SPLITS_LESS_CERTAIN = "INTRA_SEGMENT_SPLITS_LESS_CERTAIN"
    THROTTLE_CALIBRATION_DIFFERS = "THROTTLE_CALIBRATION_DIFFERS"
    DRS_SEMANTICS_UNVERIFIED = "DRS_SEMANTICS_UNVERIFIED"
    NO_TRACK_GEOMETRY = "NO_TRACK_GEOMETRY"
    ASSOCIATION_NOT_CAUSATION = "ASSOCIATION_NOT_CAUSATION"


@dataclass(frozen=True)
class Limitation:
    code: str        # a LimitationCode value - machine-readable
    message: str     # human-readable; the same text as report.limitations


class AttributionStatus(str, Enum):
    SINGLE_CONTROL_INPUT = "SINGLE_CONTROL_INPUT"    # one control input differs resolvably
    MULTI_SIGNAL = "MULTI_SIGNAL"                    # several do - no primary forced
    SPEED_ONLY = "SPEED_ONLY"                        # speed differs, no control input resolvable
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # significant, but nothing resolvable
    NOT_SIGNIFICANT = "NOT_SIGNIFICANT"              # change within the uncertainty band
    NO_DATA = "NO_DATA"                              # no telemetry coverage


# ------------------------------------------------------------- uncertainty


@dataclass(frozen=True)
class SectorAnchor:
    sector: str               # "S1" / "S2": the line at the END of that sector
    distance_a_m: float
    distance_b_m: float
    misalignment_m: float     # A - B at the same physical line


@dataclass(frozen=True)
class AlignmentUncertainty:
    misalignment_bound_m: float   # E: |misalignment| anywhere
    change_bound_m: float         # D: systematic misalignment change within one segment
    anchors: tuple[SectorAnchor, ...]
    source: str  # SECTOR_LINE_ANCHORS | PARTIAL_ANCHORS | PROVISIONAL_DEFAULT | caller label

    def band_s(self, v0_mps: float | None, v1_mps: float | None,
               walk_m: float = 0.0) -> float | None:
        if not v0_mps or not v1_mps or v0_mps <= 0 or v1_mps <= 0:
            return None
        inv0, inv1 = 1.0 / v0_mps, 1.0 / v1_mps
        return (self.misalignment_bound_m * abs(inv1 - inv0)
                + (self.change_bound_m + walk_m) * max(inv0, inv1)
                + TIMING_RESOLUTION_S)


# Speed quantization: one integer kph -> +-0.5 kph, uniform -> sd = 0.5/sqrt(3).
_QUANT_SD_MPS = SPEED_QUANTUM_KPH / 2 / 3.6 / 3 ** 0.5
WALK_SIGMAS = 3.0


def _dt2_prefix(trace: LapDistanceTrace) -> list[float]:
    """prefix[k] = sum of dt^2 over the first k real sample intervals."""
    out = [0.0]
    pts = trace.points
    for k in range(1, len(pts)):
        dt = (pts[k].ts - pts[k - 1].ts).total_seconds()
        out.append(out[-1] + (dt * dt if dt > 0 else 0.0))
    return out


def _distance_at_time(trace: LapDistanceTrace, t: float) -> float | None:
    """Integrated distance at wall-clock t, interpolated between real samples.
    None outside the trace's coverage - never extrapolated."""
    ts = [p.ts.timestamp() for p in trace.points]
    if not ts or t < ts[0] or t > ts[-1]:
        return None
    i = bisect.bisect_left(ts, t)
    if ts[i] == t:
        return trace.points[i].distance_m
    p0, p1 = trace.points[i - 1], trace.points[i]
    return p0.distance_m + (t - ts[i - 1]) / (ts[i] - ts[i - 1]) * (p1.distance_m - p0.distance_m)


def _sector_line_times(lap: Lap) -> dict[str, float]:
    out = {}
    t0 = lap.started_at.timestamp()
    if lap.sector1_s is not None:
        out["S1"] = t0 + lap.sector1_s
        if lap.sector2_s is not None:
            out["S2"] = t0 + lap.sector1_s + lap.sector2_s
    return out


def measure_alignment(trace_a: LapDistanceTrace, trace_b: LapDistanceTrace,
                      lap_a: Lap, lap_b: Lap) -> AlignmentUncertainty:
    """Misalignment of the two distance axes at the official sector lines.

    Each driver's own integrated distance at the moment it crossed a line
    (official split time) - two estimates of ONE physical point. Their
    difference is the A/B misalignment there.
    """
    ta, tb = _sector_line_times(lap_a), _sector_line_times(lap_b)
    anchors = []
    for name in ("S1", "S2"):
        if name in ta and name in tb:
            da = _distance_at_time(trace_a, ta[name])
            db = _distance_at_time(trace_b, tb[name])
            if da is not None and db is not None:
                anchors.append(SectorAnchor(name, da, db, da - db))
    if anchors:
        e = max(abs(a.misalignment_m) for a in anchors)
        source = "SECTOR_LINE_ANCHORS" if len(anchors) >= 2 else "PARTIAL_ANCHORS"
        return AlignmentUncertainty(e, e, tuple(anchors), source)
    return AlignmentUncertainty(DEFAULT_MISALIGNMENT_M, DEFAULT_MISALIGNMENT_M, (),
                                "PROVISIONAL_DEFAULT")


# ---------------------------------------------------------------- evidence


@dataclass(frozen=True)
class BrakingEvidence:
    paired: bool                      # both drivers braked in this segment
    applications_a: int
    applications_b: int
    onset_x_a: float | None
    onset_x_b: float | None
    onset_offset_m: float | None      # (A - B): negative = A braked earlier on the lap
    onset_offset_resolvable: bool
    release_x_a: float | None
    release_x_b: float | None
    release_offset_m: float | None
    release_offset_resolvable: bool
    peak_pct_a: float | None
    peak_pct_b: float | None
    speed_at_onset_a_kph: float | None
    speed_at_onset_b_kph: float | None
    zone_start_x: float
    zone_end_x: float
    delta_before_s: float             # segment start -> earliest onset
    delta_during_s: float             # earliest onset -> latest release
    delta_after_s: float              # latest release -> segment end
    band_before_s: float | None
    band_during_s: float | None
    band_after_s: float | None


@dataclass(frozen=True)
class ThrottleEvidence:
    full_level_a_pct: float | None
    full_level_b_pct: float | None
    full_modal_a_pct: float | None      # typical full reading (per-car calibration)
    full_modal_b_pct: float | None
    lift_x_a: float | None
    lift_x_b: float | None
    lift_offset_m: float | None
    lift_resolvable: bool
    application_x_a: float | None
    application_x_b: float | None
    application_offset_m: float | None   # (A - B): positive = A applied later on the lap
    application_resolvable: bool
    full_x_a: float | None
    full_x_b: float | None
    full_offset_m: float | None
    full_resolvable: bool
    minimum_a_pct: float | None
    minimum_b_pct: float | None
    mean_throttle_difference_pct: float | None  # includes per-car calibration (99 vs 100)
    delta_after_application_s: float | None     # later application -> segment end


@dataclass(frozen=True)
class SpeedEvidence:
    mean_difference_kph: float | None
    min_difference_kph: float | None
    max_difference_kph: float | None
    min_speed_a_kph: float | None
    min_speed_b_kph: float | None
    min_speed_x_a: float | None
    min_speed_x_b: float | None
    min_speed_difference_kph: float | None
    min_speed_resolvable: bool
    end_speed_a_kph: float | None
    end_speed_b_kph: float | None
    divergence_onset_x: float | None   # first point beyond E*|dv/ds| + 1 kph
    divergence_fraction: float | None


@dataclass(frozen=True)
class DifferenceRun:
    x_start: float
    x_end: float
    length_m: float
    resolvable: bool


@dataclass(frozen=True)
class CategoricalEvidence:
    available: bool
    difference_fraction: float | None
    runs: tuple[DifferenceRun, ...]
    first_resolvable_x: float | None
    min_a: int | None = None           # gear only: lowest gear observed
    min_b: int | None = None
    values_a: tuple[int, ...] = ()     # distinct raw values observed
    values_b: tuple[int, ...] = ()


@dataclass(frozen=True)
class SignalOnset:
    signal: str
    family: str
    x: float
    distance_m: float
    relation_to_midpoint: str        # BEFORE | AFTER | AT | UNDEFINED
    association: str = ASSOCIATION


@dataclass(frozen=True)
class SegmentProvenance:
    session_id: str
    driver_a: int
    lap_a: int
    driver_b: int
    lap_b: int
    grid_indices: tuple[int, int]
    sample_indices_a: tuple[int, int]
    sample_indices_b: tuple[int, int]
    ts_range_a: tuple[str, str] | None
    ts_range_b: tuple[str, str] | None
    source_provider: str | None
    calc_version: str = CALC_VERSION


@dataclass(frozen=True)
class AttributionSegment:
    region_id: str
    kind: SegmentKind
    start_index: int
    end_index: int
    x_start: float
    x_end: float
    distance_start_m: float
    distance_end_m: float
    inherited_gap_s: float | None     # delta at segment start: NOT caused here
    delta_end_s: float | None
    accumulated_change_s: float | None  # newly accumulated in this segment
    uncertainty_s: float | None
    significant: bool
    accumulation_midpoint_x: float | None
    status: AttributionStatus
    primary_signal: str | None
    supporting_signals: tuple[str, ...]
    onset_order: tuple[SignalOnset, ...]
    braking: BrakingEvidence | None
    throttle: ThrottleEvidence | None
    speed: SpeedEvidence | None
    gear: CategoricalEvidence
    drs: CategoricalEvidence
    phase_accumulation_a: dict[str, float]
    phase_accumulation_b: dict[str, float]
    dominant_phase_a: str | None
    confidence: Confidence
    provenance: SegmentProvenance


@dataclass(frozen=True)
class Accounting:
    actual_change_s: float
    attributed_change_s: float               # SINGLE_CONTROL_INPUT + MULTI_SIGNAL
    unattributed_significant_change_s: float  # SPEED_ONLY + INSUFFICIENT_EVIDENCE
    below_significance_change_s: float       # NOT_SIGNIFICANT
    unaccounted_s: float                     # actual - attributed
    change_by_status: dict[str, float]
    no_data_spans: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class SectorAttribution:
    sector: int
    official_a_s: float | None
    official_b_s: float | None
    official_delta_s: float | None    # A - B, official timing (observed)
    line_x_a: float | None            # END line of this sector on each driver's axis
    line_x_b: float | None
    line_misalignment_m: float | None
    engine_change_s: float | None     # engine delta(end line) - delta(start line)
    engine_minus_official_s: float | None
    segment_ids: tuple[str, ...]


@dataclass
class AttributionReport:
    session_id: str
    driver_a: int
    lap_a: int
    driver_b: int
    lap_b: int
    lap_length_m: float
    alignment_mode: AlignmentMode
    uncertainty: AlignmentUncertainty
    segments: list[AttributionSegment]
    accounting: Accounting
    sectors: list[SectorAttribution]
    official_lap_delta_s: float | None
    engine_delta_last_covered_s: float | None
    last_covered_x: float | None
    comparison_confidence: Confidence
    source_provider: str | None
    limitations: list[str]
    limitation_items: list[Limitation] = field(default_factory=list)
    channels: dict[str, dict[str, bool]] = field(default_factory=dict)
    sign_convention: str = SIGN_CONVENTION
    calc_version: str = CALC_VERSION


# ------------------------------------------------------------------ engine


@dataclass
class _Ctx:
    samples: list[DeltaSample]
    xs: list[float]
    d: list[float | None]
    va: list[float | None]
    vb: list[float | None]
    length: float
    u: AlignmentUncertainty
    sig_a: DriverSignals
    sig_b: DriverSignals
    trace_a: LapDistanceTrace
    trace_b: LapDistanceTrace
    step: float = field(default=0.0)
    dt2_a: list[float] = field(default_factory=list)
    dt2_b: list[float] = field(default_factory=list)

    def walk_m(self, i: int, j: int) -> float:
        """3-sigma random walk of A-B distance from speed quantization over
        the real sample intervals spanning grid points i..j (O(log n))."""
        var = 0.0
        for xs, pref in ((self.sig_a.xs, self.dt2_a), (self.sig_b.xs, self.dt2_b)):
            lo = max(bisect.bisect_right(xs, self.xs[i]) - 1, 0)
            hi = min(bisect.bisect_left(xs, self.xs[j]), len(xs) - 1)
            var += (_QUANT_SD_MPS ** 2) * (pref[hi] - pref[lo])
        return WALK_SIGMAS * var ** 0.5

    def v_mean_mps(self, i: int) -> float | None:
        a, b = self.va[i], self.vb[i]
        return (a + b) / 2 / 3.6 if a is not None and b is not None else None

    def band(self, i: int, j: int) -> float | None:
        return self.u.band_s(self.v_mean_mps(i), self.v_mean_mps(j), self.walk_m(i, j))

    def grid_at(self, x: float, lo: int, hi: int) -> int:
        return min(max(bisect.bisect_left(self.xs, x - 1e-12), lo), hi)


def _covered_runs(d: list[float | None]) -> list[tuple[int, int]]:
    runs, i, n = [], 0, len(d)
    while i < n:
        if d[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and d[j + 1] is not None:
            j += 1
        if j > i:
            runs.append((i, j))
        i = j + 1
    return runs


def _brake_intervals(sig: DriverSignals) -> list[tuple[float, float]]:
    out = []
    for app in sig.brake_applications:
        x0 = app.onset.x_before if app.onset.x_before is not None else app.onset.x_at
        x1 = app.release.x_at if app.release else sig.xs[-1]
        out.append((x0, x1))
    return out


def _merge(intervals: list[tuple[float, float]]) -> list[list[float]]:
    merged: list[list[float]] = []
    for x0, x1 in sorted(intervals):
        if merged and x0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return merged


def _boundaries(ctx: _Ctx, lo: int, hi: int, zones: list[list[float]]) -> list[int]:
    zs = [list(z) for z in zones if z[1] >= ctx.xs[lo] and z[0] <= ctx.xs[hi]]
    bounds = [lo]
    k = 0
    while k < len(zs) - 1:
        j0 = max(bisect.bisect_right(ctx.xs, zs[k][1]), lo)
        j1 = min(bisect.bisect_left(ctx.xs, zs[k + 1][0]) - 1, hi)
        best, best_v = None, None
        for j in range(j0, j1 + 1):
            v = ctx.v_mean_mps(j)
            if v is not None and (best_v is None or v > best_v):
                best, best_v = j, v
        if best is None:  # no straight between them: one braking complex
            zs[k][1] = max(zs[k][1], zs[k + 1][1])
            del zs[k + 1]
            continue
        if best > bounds[-1]:
            bounds.append(best)
        k += 1
    if hi > bounds[-1]:
        bounds.append(hi)
    return bounds


def _resolvable(ta: Transition | None, tb: Transition | None, e: float, length: float) -> bool:
    """Both changes are bracketed (x_before, x_at]. Resolvable only if the two
    brackets are separated by more than the misalignment bound."""
    if ta is None or tb is None or ta.x_before is None or tb.x_before is None:
        return False
    gap = max(tb.x_before - ta.x_at, ta.x_before - tb.x_at, 0.0) * length
    return gap > e


def _offset(ta: Transition | None, tb: Transition | None, length: float) -> float | None:
    if ta is None or tb is None:
        return None
    return (ta.x_at - tb.x_at) * length


def _in(x: float, x0: float, x1: float) -> bool:
    return x0 - 1e-12 <= x <= x1 + 1e-12


def _braking(ctx: _Ctx, lo: int, hi: int) -> BrakingEvidence | None:
    if not (ctx.sig_a.brake_available and ctx.sig_b.brake_available):
        return None  # a missing channel is not "did not brake"
    x0, x1 = ctx.xs[lo], ctx.xs[hi]
    apps_a = [a for a in ctx.sig_a.brake_applications if _in(a.onset.x_at, x0, x1)]
    apps_b = [a for a in ctx.sig_b.brake_applications if _in(a.onset.x_at, x0, x1)]
    if not apps_a and not apps_b:
        return None
    on_a = apps_a[0].onset if apps_a else None
    on_b = apps_b[0].onset if apps_b else None
    rel_a = apps_a[-1].release if apps_a else None
    rel_b = apps_b[-1].release if apps_b else None
    onsets = [t.x_at for t in (on_a, on_b) if t is not None]
    releases = [t.x_at for t in (rel_a, rel_b) if t is not None]
    zs = min(onsets)
    ze = max(releases) if releases else x1
    izs = ctx.grid_at(zs, lo, hi)
    ize = max(ctx.grid_at(ze, lo, hi), izs)
    d = ctx.d
    return BrakingEvidence(
        paired=bool(apps_a and apps_b), applications_a=len(apps_a), applications_b=len(apps_b),
        onset_x_a=on_a.x_at if on_a else None, onset_x_b=on_b.x_at if on_b else None,
        onset_offset_m=_offset(on_a, on_b, ctx.length),
        onset_offset_resolvable=_resolvable(on_a, on_b, ctx.u.misalignment_bound_m, ctx.length),
        release_x_a=rel_a.x_at if rel_a else None, release_x_b=rel_b.x_at if rel_b else None,
        release_offset_m=_offset(rel_a, rel_b, ctx.length),
        release_offset_resolvable=_resolvable(rel_a, rel_b, ctx.u.misalignment_bound_m,
                                              ctx.length),
        peak_pct_a=max(a.peak_pct for a in apps_a) if apps_a else None,
        peak_pct_b=max(a.peak_pct for a in apps_b) if apps_b else None,
        speed_at_onset_a_kph=apps_a[0].speed_at_onset_kph if apps_a else None,
        speed_at_onset_b_kph=apps_b[0].speed_at_onset_kph if apps_b else None,
        zone_start_x=ctx.xs[izs], zone_end_x=ctx.xs[ize],
        delta_before_s=d[izs] - d[lo], delta_during_s=d[ize] - d[izs],
        delta_after_s=d[hi] - d[ize],
        band_before_s=ctx.band(lo, izs), band_during_s=ctx.band(izs, ize),
        band_after_s=ctx.band(ize, hi))


def _lift_for(sig: DriverSignals, x0: float, x1: float):
    for lift in sig.throttle_lifts:
        if lift.braking_indices and _in(sig.xs[lift.braking_indices[0]], x0, x1):
            return lift
    for lift in sig.throttle_lifts:
        if _in(lift.lift.x_at, x0, x1):
            return lift
    return None


def _throttle(ctx: _Ctx, lo: int, hi: int) -> ThrottleEvidence | None:
    x0, x1 = ctx.xs[lo], ctx.xs[hi]
    la, lb = _lift_for(ctx.sig_a, x0, x1), _lift_for(ctx.sig_b, x0, x1)
    if la is None and lb is None:
        return None
    e, n = ctx.u.misalignment_bound_m, ctx.length

    def part(lift, name):
        return getattr(lift, name) if lift is not None else None

    app_a, app_b = part(la, "application"), part(lb, "application")
    later = max((t.x_at for t in (app_a, app_b) if t is not None), default=None)
    after = None
    if later is not None and _in(later, x0, x1):
        after = ctx.d[hi] - ctx.d[ctx.grid_at(later, lo, hi)]
    diffs = [ctx.samples[i].continuous_delta.get("throttle_pct") for i in range(lo, hi + 1)]
    diffs = [v for v in diffs if v is not None]
    return ThrottleEvidence(
        full_level_a_pct=ctx.sig_a.full_throttle_pct, full_level_b_pct=ctx.sig_b.full_throttle_pct,
        full_modal_a_pct=ctx.sig_a.full_throttle_modal_pct,
        full_modal_b_pct=ctx.sig_b.full_throttle_modal_pct,
        lift_x_a=la.lift.x_at if la else None, lift_x_b=lb.lift.x_at if lb else None,
        lift_offset_m=_offset(part(la, "lift"), part(lb, "lift"), n),
        lift_resolvable=_resolvable(part(la, "lift"), part(lb, "lift"), e, n),
        application_x_a=app_a.x_at if app_a else None,
        application_x_b=app_b.x_at if app_b else None,
        application_offset_m=_offset(app_a, app_b, n),
        application_resolvable=_resolvable(app_a, app_b, e, n),
        full_x_a=la.full.x_at if la and la.full else None,
        full_x_b=lb.full.x_at if lb and lb.full else None,
        full_offset_m=_offset(part(la, "full"), part(lb, "full"), n),
        full_resolvable=_resolvable(part(la, "full"), part(lb, "full"), e, n),
        minimum_a_pct=la.minimum_pct if la else None, minimum_b_pct=lb.minimum_pct if lb else None,
        mean_throttle_difference_pct=sum(diffs) / len(diffs) if diffs else None,
        delta_after_application_s=after)


def _points_in(trace: LapDistanceTrace, xs: list[float], x0: float, x1: float):
    lo, hi = _sample_range(xs, x0, x1)  # O(log n): xs are the trace's own positions
    return trace.points[lo:hi + 1]


def _raw_min_speed(trace: LapDistanceTrace, xs: list[float], x0: float, x1: float):
    best = None
    for p in _points_in(trace, xs, x0, x1):
        if p.speed_kph is not None and (best is None or p.speed_kph < best.speed_kph):
            best = p
    return (best.speed_kph, best.normalized_distance) if best else (None, None)


def _speed(ctx: _Ctx, lo: int, hi: int) -> SpeedEvidence:
    dv = [ctx.samples[i].continuous_delta.get("speed_kph") for i in range(lo, hi + 1)]
    known = [v for v in dv if v is not None]
    x0, x1 = ctx.xs[lo], ctx.xs[hi]
    min_a, mx_a = _raw_min_speed(ctx.trace_a, ctx.sig_a.xs, x0, x1)
    min_b, mx_b = _raw_min_speed(ctx.trace_b, ctx.sig_b.xs, x0, x1)
    onset, divergent = None, 0
    grid_m = ctx.step * ctx.length
    for k, i in enumerate(range(lo, hi + 1)):
        if dv[k] is None:
            continue
        i0, i1 = max(i - 1, lo), min(i + 1, hi)
        va0, vb0, va1, vb1 = ctx.va[i0], ctx.vb[i0], ctx.va[i1], ctx.vb[i1]
        if None in (va0, vb0, va1, vb1) or i1 == i0:
            continue
        dvds = ((va1 + vb1) / 2 - (va0 + vb0) / 2) / ((i1 - i0) * grid_m)
        if abs(dv[k]) > ctx.u.misalignment_bound_m * abs(dvds) + SPEED_QUANTUM_KPH:
            divergent += 1
            if onset is None:
                onset = ctx.xs[i]
    min_diff = min_a - min_b if min_a is not None and min_b is not None else None
    return SpeedEvidence(
        mean_difference_kph=sum(known) / len(known) if known else None,
        min_difference_kph=min(known) if known else None,
        max_difference_kph=max(known) if known else None,
        min_speed_a_kph=min_a, min_speed_b_kph=min_b, min_speed_x_a=mx_a, min_speed_x_b=mx_b,
        min_speed_difference_kph=min_diff,
        min_speed_resolvable=min_diff is not None and abs(min_diff) > SPEED_QUANTUM_KPH,
        end_speed_a_kph=ctx.va[hi], end_speed_b_kph=ctx.vb[hi],
        divergence_onset_x=onset,
        divergence_fraction=divergent / len(known) if known else None)


def _max_spacing(xs: list[float], x0: float, x1: float) -> float:
    lo = max(bisect.bisect_right(xs, x0) - 1, 0)
    hi = min(bisect.bisect_left(xs, x1) + 1, len(xs) - 1)
    return max((xs[k + 1] - xs[k] for k in range(lo, hi)), default=0.0)


def _categorical(ctx: _Ctx, fname: str, lo: int, hi: int) -> CategoricalEvidence:
    flags = [ctx.samples[i].discrete_differs.get(fname) for i in range(lo, hi + 1)]
    known = [f for f in flags if f is not None]
    x0, x1 = ctx.xs[lo], ctx.xs[hi]
    raw_a = [getattr(p, fname) for p in _points_in(ctx.trace_a, ctx.sig_a.xs, x0, x1)
             if getattr(p, fname) is not None]
    raw_b = [getattr(p, fname) for p in _points_in(ctx.trace_b, ctx.sig_b.xs, x0, x1)
             if getattr(p, fname) is not None]
    if not known:
        return CategoricalEvidence(available=False, difference_fraction=None, runs=(),
                                   first_resolvable_x=None)
    runs, k = [], 0
    while k < len(flags):
        if flags[k] is not True:
            k += 1
            continue
        s = k
        while k + 1 < len(flags) and flags[k + 1] is True:
            k += 1
        xs_, xe = ctx.xs[lo + s], ctx.xs[lo + k]
        length = (xe - xs_) * ctx.length
        h = max(_max_spacing(ctx.sig_a.xs, xs_, xe), _max_spacing(ctx.sig_b.xs, xs_, xe))
        runs.append(DifferenceRun(xs_, xe, length,
                                  length > ctx.u.misalignment_bound_m + h * ctx.length))
        k += 1
    first = next((r.x_start for r in runs if r.resolvable), None)
    is_gear = fname == "gear"
    return CategoricalEvidence(
        available=True, difference_fraction=sum(known) / len(known), runs=tuple(runs),
        first_resolvable_x=first,
        min_a=int(min(raw_a)) if is_gear and raw_a else None,
        min_b=int(min(raw_b)) if is_gear and raw_b else None,
        values_a=tuple(sorted({int(v) for v in raw_a})),
        values_b=tuple(sorted({int(v) for v in raw_b})))


def _phase_accumulation(ctx: _Ctx, sig: DriverSignals, lo: int, hi: int) -> dict[str, float]:
    acc: dict[str, float] = {}
    for i in range(lo, hi):
        k = bisect.bisect_right(sig.xs, ctx.xs[i] + 1e-12) - 1
        ph = sig.phases[k].value if k >= 0 else Phase.UNKNOWN.value
        acc[ph] = acc.get(ph, 0.0) + (ctx.d[i + 1] - ctx.d[i])
    return acc


def _midpoint(ctx: _Ctx, lo: int, hi: int) -> float | None:
    change = ctx.d[hi] - ctx.d[lo]
    if change == 0:
        return None
    for i in range(lo, hi + 1):
        if (ctx.d[i] - ctx.d[lo]) / change >= 0.5:
            return ctx.xs[i]
    return None


def _onsets(ctx: _Ctx, braking, throttle, speed, gear, drs, mid) -> list[SignalOnset]:
    cands: list[tuple[str, str, float]] = []
    if braking is not None:
        if braking.paired and braking.onset_offset_resolvable:
            cands.append(("brake_onset", "brake", min(braking.onset_x_a, braking.onset_x_b)))
        if braking.paired and braking.release_offset_resolvable:
            cands.append(("brake_release", "brake",
                          min(braking.release_x_a, braking.release_x_b)))
        if not braking.paired:
            cands.append(("brake_unpaired", "brake",
                          braking.onset_x_a if braking.onset_x_a is not None
                          else braking.onset_x_b))
    if throttle is not None:
        for name, flag, xa, xb in (
                ("throttle_lift", throttle.lift_resolvable, throttle.lift_x_a, throttle.lift_x_b),
                ("throttle_application", throttle.application_resolvable,
                 throttle.application_x_a, throttle.application_x_b),
                ("full_throttle", throttle.full_resolvable, throttle.full_x_a, throttle.full_x_b)):
            if flag:
                cands.append((name, "throttle", min(xa, xb)))
    if speed is not None and speed.divergence_onset_x is not None:
        cands.append(("speed", "speed", speed.divergence_onset_x))
    for name, ev in (("gear", gear), ("drs", drs)):
        if ev.first_resolvable_x is not None:
            cands.append((name, name, ev.first_resolvable_x))
    out = []
    for name, fam, x in sorted(cands, key=lambda c: (c[2], c[0])):
        if mid is None:
            rel = "UNDEFINED"
        elif x < mid - 1e-12:
            rel = "BEFORE"
        elif x > mid + 1e-12:
            rel = "AFTER"
        else:
            rel = "AT"
        out.append(SignalOnset(name, fam, x, x * ctx.length, rel))
    return out


def _sample_range(xs: list[float], x0: float, x1: float) -> tuple[int, int]:
    return bisect.bisect_left(xs, x0 - 1e-12), bisect.bisect_right(xs, x1 + 1e-12) - 1


def _ts_range(trace: LapDistanceTrace, rng: tuple[int, int]) -> tuple[str, str] | None:
    lo, hi = rng
    if hi < lo:
        return None
    return trace.points[lo].ts.isoformat(), trace.points[hi].ts.isoformat()


def _segment(ctx: _Ctx, rid: str, lo: int, hi: int, prov_base: dict,
             no_data: bool = False) -> AttributionSegment:
    xs, d = ctx.xs, ctx.d
    ra = _sample_range(ctx.sig_a.xs, xs[lo], xs[hi])
    rb = _sample_range(ctx.sig_b.xs, xs[lo], xs[hi])
    prov = SegmentProvenance(**prov_base, grid_indices=(lo, hi), sample_indices_a=ra,
                             sample_indices_b=rb, ts_range_a=_ts_range(ctx.trace_a, ra),
                             ts_range_b=_ts_range(ctx.trace_b, rb))
    empty = CategoricalEvidence(available=False, difference_fraction=None, runs=(),
                                first_resolvable_x=None)
    common = {"region_id": rid, "start_index": lo, "end_index": hi, "x_start": xs[lo], "x_end": xs[hi],
                  "distance_start_m": xs[lo] * ctx.length, "distance_end_m": xs[hi] * ctx.length,
                  "provenance": prov}
    if no_data:
        return AttributionSegment(
            **common, kind=SegmentKind.NO_DATA, inherited_gap_s=d[lo], delta_end_s=None,
            accumulated_change_s=None, uncertainty_s=None, significant=False,
            accumulation_midpoint_x=None, status=AttributionStatus.NO_DATA,
            primary_signal=None, supporting_signals=(), onset_order=(), braking=None,
            throttle=None, speed=None, gear=empty, drs=empty, phase_accumulation_a={},
            phase_accumulation_b={}, dominant_phase_a=None, confidence=Confidence.NONE)

    change = d[hi] - d[lo]
    band = ctx.band(lo, hi)
    significant = band is not None and abs(change) > band
    if not significant:
        kind = SegmentKind.STABLE
    elif change > 0:
        kind = SegmentKind.LOSING
    else:
        kind = SegmentKind.RECOVERING if d[lo] > 0 else SegmentKind.GAINING
    confidence = min((ctx.samples[i].confidence for i in range(lo, hi + 1)), key=confidence_rank)

    braking, throttle = _braking(ctx, lo, hi), _throttle(ctx, lo, hi)
    speed = _speed(ctx, lo, hi)
    gear, drs = _categorical(ctx, "gear", lo, hi), _categorical(ctx, "drs", lo, hi)
    mid = _midpoint(ctx, lo, hi)
    onsets = _onsets(ctx, braking, throttle, speed, gear, drs, mid)
    families = []
    for o in onsets:
        if o.family != "speed" and o.family not in families:
            families.append(o.family)
    has_speed = speed.divergence_onset_x is not None

    primary, supporting = None, ()
    if not significant:
        status = AttributionStatus.NOT_SIGNIFICANT
    elif confidence is Confidence.NONE:
        status = AttributionStatus.INSUFFICIENT_EVIDENCE
    elif len(families) == 1:
        status, primary = AttributionStatus.SINGLE_CONTROL_INPUT, families[0]
        supporting = ("speed",) if has_speed else ()
    elif len(families) > 1:
        status = AttributionStatus.MULTI_SIGNAL
        supporting = tuple(families) + (("speed",) if has_speed else ())
    elif has_speed:
        status, primary = AttributionStatus.SPEED_ONLY, "speed"
    else:
        status = AttributionStatus.INSUFFICIENT_EVIDENCE

    acc_a = _phase_accumulation(ctx, ctx.sig_a, lo, hi)
    acc_b = _phase_accumulation(ctx, ctx.sig_b, lo, hi)
    dominant = None
    if change != 0 and acc_a:
        dominant = max(sorted(acc_a), key=lambda p: acc_a[p] * (1 if change > 0 else -1))
    return AttributionSegment(
        **common, kind=kind, inherited_gap_s=d[lo], delta_end_s=d[hi],
        accumulated_change_s=change, uncertainty_s=band, significant=significant,
        accumulation_midpoint_x=mid, status=status, primary_signal=primary,
        supporting_signals=supporting, onset_order=tuple(onsets), braking=braking,
        throttle=throttle, speed=speed, gear=gear, drs=drs, phase_accumulation_a=acc_a,
        phase_accumulation_b=acc_b, dominant_phase_a=dominant, confidence=confidence)


def _delta_at_x(ctx: _Ctx, x: float) -> float | None:
    """Linear interpolation of the 10.2 delta curve between grid points."""
    if x < ctx.xs[0] or x > ctx.xs[-1]:
        return None
    i = bisect.bisect_left(ctx.xs, x)
    if ctx.xs[i] == x:
        return ctx.d[i]
    d0, d1 = ctx.d[i - 1], ctx.d[i]
    if d0 is None or d1 is None:
        return None
    return d0 + (x - ctx.xs[i - 1]) / (ctx.xs[i] - ctx.xs[i - 1]) * (d1 - d0)


def _sectors(ctx: _Ctx, lap_a: Lap, lap_b: Lap,
             segments: list[AttributionSegment]) -> list[SectorAttribution]:
    anchors = {a.sector: a for a in ctx.u.anchors}
    out = []
    prev_x: float | None = 0.0
    for n, key in ((1, "S1"), (2, "S2"), (3, None)):
        oa, ob = getattr(lap_a, f"sector{n}_s"), getattr(lap_b, f"sector{n}_s")
        official = oa - ob if oa is not None and ob is not None else None
        anc = anchors.get(key) if key else None
        xa = anc.distance_a_m / ctx.length if anc else None
        xb = anc.distance_b_m / ctx.length if anc else None
        end_x = (xa + xb) / 2 if anc else None  # S3 ends at the finish: not covered here
        engine = None
        if prev_x is not None and end_x is not None:
            d0, d1 = _delta_at_x(ctx, prev_x), _delta_at_x(ctx, end_x)
            engine = d1 - d0 if d0 is not None and d1 is not None else None
        lo_x = prev_x if prev_x is not None else 1.0
        hi_x = end_x if end_x is not None else 1.0
        ids = tuple(s.region_id for s in segments
                    if s.kind is not SegmentKind.NO_DATA and s.x_end > lo_x and s.x_start < hi_x)
        out.append(SectorAttribution(
            sector=n, official_a_s=oa, official_b_s=ob, official_delta_s=official,
            line_x_a=xa, line_x_b=xb, line_misalignment_m=anc.misalignment_m if anc else None,
            engine_change_s=engine,
            engine_minus_official_s=(engine - official
                                     if engine is not None and official is not None else None),
            segment_ids=ids))
        prev_x = end_x
    return out


def _infer_mode(analysis: DeltaAnalysis) -> AlignmentMode:
    cmp = analysis.comparison
    if cmp.trace_a.time_origin is not None or cmp.trace_b.time_origin is not None:
        return AlignmentMode.POSITION_PROJECTED  # only 10.3 sets time_origin
    return AlignmentMode.NORMALIZED_DISTANCE


def attribute_comparison(analysis: DeltaAnalysis, lap_a: Lap, lap_b: Lap,
                         uncertainty: AlignmentUncertainty | None = None,
                         alignment_mode: AlignmentMode | None = None) -> AttributionReport:
    """Segment, measure and attribute one 10.2 DeltaAnalysis. Pure, O(n)."""
    cmp = analysis.comparison
    if (lap_a.driver_number, lap_a.lap_number) != (cmp.driver_a, cmp.lap_number_a) or (
            lap_b.driver_number, lap_b.lap_number) != (cmp.driver_b, cmp.lap_number_b):
        raise ValueError("laps do not match the comparison's drivers/laps")
    sig_a, sig_b = detect_signals(cmp.trace_a), detect_signals(cmp.trace_b)
    u = uncertainty or measure_alignment(cmp.trace_a, cmp.trace_b, lap_a, lap_b)
    samples = analysis.samples
    xs = [s.x for s in samples]
    ctx = _Ctx(samples=samples, xs=xs, d=[s.delta_t_s for s in samples],
               va=[s.a.get("speed_kph") for s in samples],
               vb=[s.b.get("speed_kph") for s in samples],
               length=cmp.lap_length_m, u=u, sig_a=sig_a, sig_b=sig_b,
               trace_a=cmp.trace_a, trace_b=cmp.trace_b,
               step=(xs[1] - xs[0]) if len(xs) > 1 else 0.0,
               dt2_a=_dt2_prefix(cmp.trace_a), dt2_b=_dt2_prefix(cmp.trace_b))
    source = lap_a.provenance.provider.value if lap_a.provenance else None
    prov_base = {"session_id": cmp.session_id, "driver_a": cmp.driver_a, "lap_a": cmp.lap_number_a,
                     "driver_b": cmp.driver_b, "lap_b": cmp.lap_number_b, "source_provider": source}

    zones = _merge(_brake_intervals(sig_a) + _brake_intervals(sig_b)) if (
        sig_a.brake_available and sig_b.brake_available) else []
    spans: list[tuple[int, int, bool]] = []
    cursor = 0
    for lo, hi in _covered_runs(ctx.d):
        if lo > cursor:
            spans.append((cursor, lo, True))
        b = _boundaries(ctx, lo, hi, zones)
        spans.extend((b[k], b[k + 1], False) for k in range(len(b) - 1))
        cursor = hi
    if cursor < len(xs) - 1:
        spans.append((cursor, len(xs) - 1, True))

    segments = [_segment(ctx, f"R{k + 1:02d}", lo, hi, prov_base, no_data=nd)
                for k, (lo, hi, nd) in enumerate(spans)]

    by_status: dict[str, float] = {}
    for s in segments:
        if s.accumulated_change_s is not None:
            by_status[s.status.value] = by_status.get(s.status.value, 0.0) + s.accumulated_change_s
    actual = sum(ctx.d[hi] - ctx.d[lo] for lo, hi in _covered_runs(ctx.d))
    attributed = (by_status.get("SINGLE_CONTROL_INPUT", 0.0)
                  + by_status.get("MULTI_SIGNAL", 0.0))
    accounting = Accounting(
        actual_change_s=actual, attributed_change_s=attributed,
        unattributed_significant_change_s=(by_status.get("SPEED_ONLY", 0.0)
                                           + by_status.get("INSUFFICIENT_EVIDENCE", 0.0)),
        below_significance_change_s=by_status.get("NOT_SIGNIFICANT", 0.0),
        unaccounted_s=actual - attributed, change_by_status=by_status,
        no_data_spans=tuple((s.x_start, s.x_end) for s in segments
                            if s.kind is SegmentKind.NO_DATA))

    covered = [i for i, v in enumerate(ctx.d) if v is not None]
    official = (lap_a.duration_s - lap_b.duration_s
                if lap_a.duration_s is not None and lap_b.duration_s is not None else None)
    mode = alignment_mode or _infer_mode(analysis)
    items = _limitations(mode, u, sig_a, sig_b, segments)
    return AttributionReport(
        session_id=cmp.session_id, driver_a=cmp.driver_a, lap_a=cmp.lap_number_a,
        driver_b=cmp.driver_b, lap_b=cmp.lap_number_b, lap_length_m=cmp.lap_length_m,
        alignment_mode=mode, uncertainty=u, segments=segments, accounting=accounting,
        sectors=_sectors(ctx, lap_a, lap_b, segments), official_lap_delta_s=official,
        engine_delta_last_covered_s=ctx.d[covered[-1]] if covered else None,
        last_covered_x=xs[covered[-1]] if covered else None,
        comparison_confidence=cmp.confidence, source_provider=source,
        limitations=[x.message for x in items], limitation_items=items,
        channels={"a": _channels(sig_a), "b": _channels(sig_b)})


def _channels(sig: DriverSignals) -> dict[str, bool]:
    return {"brake": sig.brake_available, "throttle": sig.throttle_available,
            "gear": sig.gear_available, "drs": sig.drs_available}


def _limitations(mode, u, sig_a, sig_b, segments) -> list[Limitation]:
    out: list[Limitation] = []

    def add(code: LimitationCode, message: str) -> None:
        out.append(Limitation(code.value, message))

    if mode is AlignmentMode.NORMALIZED_DISTANCE:
        add(LimitationCode.ALIGNMENT_NORMALIZED_DISTANCE,
            "NORMALIZED_DISTANCE: positions are 10.1B integrated distance divided by "
            "the cited lap length, not physical track coordinates")
    elif mode is AlignmentMode.POSITION_PROJECTED:
        add(LimitationCode.ALIGNMENT_POSITION_PROJECTED_UNVALIDATED,
            "POSITION_PROJECTED: Phase 10.3 projection is not validated on real data "
            "(its S2 real-data check failed)")
    if u.source == "PROVISIONAL_DEFAULT":
        add(LimitationCode.UNCERTAINTY_DEFAULT_PROVISIONAL,
            f"PROVISIONAL: no official sector anchors; misalignment bound defaults to "
            f"{DEFAULT_MISALIGNMENT_M} m measured on the Singapore 2023 pair")
    elif u.source == "PARTIAL_ANCHORS":
        add(LimitationCode.UNCERTAINTY_SINGLE_ANCHOR,
            "PROVISIONAL: one sector anchor only; the misalignment bound rests on a "
            "single measurement")
    else:
        add(LimitationCode.UNCERTAINTY_ANCHORS_LOWER_BOUND,
            f"misalignment bound measured at {len(u.anchors)} official sector lines "
            f"only; it can be exceeded between them, so a significant segment is one "
            f"not explained by the MEASURED misalignment")
    add(LimitationCode.UNCERTAINTY_WITHIN_SEGMENT_PROVISIONAL,
        "PROVISIONAL: within-segment misalignment change is bounded by the "
        "misalignment bound itself (D = E); not yet calibrated on more real pairs")
    missing = [(LimitationCode.BRAKE_CHANNEL_MISSING, "brake", "brake_available",
                ("no braking zones, no straight-to-straight segmentation, no braking "
                 "comparison")),
               (LimitationCode.THROTTLE_CHANNEL_MISSING, "throttle", "throttle_available",
                "no throttle lift/application/full comparison"),
               (LimitationCode.GEAR_CHANNEL_MISSING, "gear", "gear_available",
                "no gear comparison"),
               (LimitationCode.DRS_CHANNEL_MISSING, "DRS", "drs_available",
                "no DRS comparison")]
    for code, label, attr, effect in missing:
        absent = [who for who, sig in (("A", sig_a), ("B", sig_b)) if not getattr(sig, attr)]
        if absent:
            add(code, f"{label} channel missing for driver {'/'.join(absent)}: {effect}")
    if any(s.kind is SegmentKind.NO_DATA for s in segments):
        add(LimitationCode.TELEMETRY_COVERAGE_INCOMPLETE,
            "NO_DATA spans have no delta; nothing is attributed there")
    add(LimitationCode.INTRA_SEGMENT_SPLITS_LESS_CERTAIN,
        "intra-segment splits (braking before/during/after, per-phase accumulation) "
        "end at changing speed and carry larger alignment uncertainty than the "
        "straight-to-straight segment total")
    if sig_a.full_throttle_modal_pct != sig_b.full_throttle_modal_pct:
        add(LimitationCode.THROTTLE_CALIBRATION_DIFFERS,
            f"typical full-throttle value differs per car (A "
            f"{sig_a.full_throttle_modal_pct}, B {sig_b.full_throttle_modal_pct}): "
            f"mean throttle differences include calibration, not only driver input")
    add(LimitationCode.DRS_SEMANTICS_UNVERIFIED,
        "DRS codes are compared for equality only; their open/closed meaning is not "
        "verified in this repository")
    add(LimitationCode.NO_TRACK_GEOMETRY,
        "no track geometry: no apex, corner name or corner identity is available")
    add(LimitationCode.ASSOCIATION_NOT_CAUSATION, "associations are temporal, never causal")
    return out


# --------------------------------------------------------- serialization


def _plain(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {str(_plain(k)): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


def report_to_dict(report: AttributionReport) -> dict[str, Any]:
    """Deterministic, JSON-ready. No wall-clock timestamps: re-running the
    same input yields byte-identical JSON."""
    return _plain(dataclasses.asdict(report))


def _fmt(v: float | None, unit: str = "s", signed: bool = True) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.3f} {unit}" if signed else f"{v:.3f} {unit}"


def attribution_facts(report: AttributionReport) -> dict[str, Any]:
    """Phase 10.5 context pack: bounded, deterministic facts - no raw telemetry."""
    facts = []
    u = report.uncertainty
    facts.append(_fact(
        "attr_summary", "C",
        f"#{report.driver_a} lap {report.lap_a} vs #{report.driver_b} lap {report.lap_b}: "
        f"official lap delta {_fmt(report.official_lap_delta_s)} (A-B); engine delta at the "
        f"last covered position x={report.last_covered_x} is "
        f"{_fmt(report.engine_delta_last_covered_s)}; alignment {report.alignment_mode.value}, "
        f"misalignment bound {u.misalignment_bound_m:.2f} m ({u.source})",
        {"official_lap_delta_s": report.official_lap_delta_s,
         "engine_delta_last_covered_s": report.engine_delta_last_covered_s,
         "alignment_mode": report.alignment_mode.value,
         "misalignment_bound_m": u.misalignment_bound_m, "uncertainty_source": u.source,
         "sign_convention": report.sign_convention},
        report.comparison_confidence.value))
    acc = report.accounting
    facts.append(_fact(
        "attr_accounting", "C",
        f"delta change over covered distance {_fmt(acc.actual_change_s)}: "
        f"{_fmt(acc.attributed_change_s)} in segments with resolvable control-input "
        f"differences, {_fmt(acc.unattributed_significant_change_s)} significant without "
        f"one, {_fmt(acc.below_significance_change_s)} within uncertainty",
        {"actual_change_s": acc.actual_change_s, "attributed_change_s": acc.attributed_change_s,
         "unattributed_significant_change_s": acc.unattributed_significant_change_s,
         "below_significance_change_s": acc.below_significance_change_s,
         "unaccounted_s": acc.unaccounted_s}))
    for sec in report.sectors:
        facts.append(_fact(
            f"attr_sector{sec.sector}", "B" if sec.engine_change_s is None else "C",
            f"sector {sec.sector}: official A-B {_fmt(sec.official_delta_s)}; engine "
            f"{_fmt(sec.engine_change_s)}",
            {"official_delta_s": sec.official_delta_s, "engine_change_s": sec.engine_change_s,
             "engine_minus_official_s": sec.engine_minus_official_s,
             "segment_ids": list(sec.segment_ids)}))
    for s in report.segments:
        if s.kind is SegmentKind.NO_DATA:
            continue
        br, th, sp = s.braking, s.throttle, s.speed
        facts.append(_fact(
            f"seg_{s.region_id}", "C",
            f"{s.region_id} ({s.distance_start_m:.0f}-{s.distance_end_m:.0f} m): delta "
            f"{_fmt(s.inherited_gap_s)} -> {_fmt(s.delta_end_s)}, accumulated "
            f"{_fmt(s.accumulated_change_s)} +/- {_fmt(s.uncertainty_s, signed=False)} "
            f"({s.kind.value}, {'significant' if s.significant else 'not significant'}); "
            f"evidence {s.status.value}"
            + (f", in order: {', '.join(o.signal for o in s.onset_order)}"
               if s.onset_order else ""),
            {"region_id": s.region_id, "x_start": s.x_start, "x_end": s.x_end,
             "distance_start_m": s.distance_start_m, "distance_end_m": s.distance_end_m,
             "direction": s.kind.value, "inherited_gap_s": s.inherited_gap_s,
             "accumulated_change_s": s.accumulated_change_s, "uncertainty_s": s.uncertainty_s,
             "significant": s.significant, "phase": s.dominant_phase_a,
             "status": s.status.value, "primary_signal": s.primary_signal,
             "supporting_signals": list(s.supporting_signals),
             "onset_order": [o.signal for o in s.onset_order],
             "speed_delta_mean_kph": sp.mean_difference_kph if sp else None,
             "min_speed_difference_kph": sp.min_speed_difference_kph if sp else None,
             "brake_onset_offset_m": br.onset_offset_m if br else None,
             "brake_onset_resolvable": br.onset_offset_resolvable if br else None,
             "throttle_application_offset_m": th.application_offset_m if th else None,
             "throttle_application_resolvable": th.application_resolvable if th else None,
             "gear_difference_fraction": s.gear.difference_fraction,
             "drs_difference_fraction": s.drs.difference_fraction,
             "alignment_mode": report.alignment_mode.value,
             "association": ASSOCIATION},
            s.confidence.value))
    return {"pack": "lap_attribution_v1", "session_id": report.session_id,
            "calc_version": report.calc_version, "facts": facts,
            "limitations": list(report.limitations)}
