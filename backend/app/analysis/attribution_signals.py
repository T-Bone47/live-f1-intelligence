"""Phase 10.4: per-driver control-input events from a 10.1B trace.

Reads the REAL samples of one normalized LapDistanceTrace - never the 10.2
interpolated grid, where a 0->100 brake step becomes a fabricated 50. Every
state change is located between two real samples: it happened somewhere in
(x_before, x_at]. x_at is the first sample OBSERVED in the new state;
x_before is the last sample observed in the old one. A state already held
at the trace's first sample has x_before=None (censored: the change itself
was never observed).

Signals (only from channels the source actually provides):
- brake: on = brake_pct > 0 (the real feed is binary 0/100, verified in
  scripts/fixtures/real-openf1-pair). Onset, peak, release.
- throttle: "full" is per car, not a fixed 100 - on the real Singapore pair
  #55 holds 99 on straights while #63 holds 100. Full = within one integer
  quantum of that trace's own maximum. A throttle lift is a run of non-full
  samples holding at most ONE braking zone (split at each further brake
  onset); within it: minimum, application (first rise after the last
  minimum sample after braking - the start of the FINAL rise), full regained
  (None when the next braking comes first).
- gear: changes between consecutive real samples; integers, never blended.

Phases (no track geometry exists, so no APEX is ever claimed):
FULL_THROTTLE | LIFT (partial throttle before braking, or a lift without
braking before the throttle rises) | BRAKING | TRANSITION (brake released,
throttle not yet rising) | EXIT (throttle rising, not yet full) | UNKNOWN
(brake or throttle missing on that sample).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import pairwise

from app.analysis.lap_distance import LapDistanceTrace

# The real feed carries integer throttle and speed (verified on the
# Singapore fixture); one quantum is the smallest observable difference.
THROTTLE_QUANTUM_PCT = 1.0
SPEED_QUANTUM_KPH = 1.0


class Phase(str, Enum):
    FULL_THROTTLE = "FULL_THROTTLE"
    LIFT = "LIFT"
    BRAKING = "BRAKING"
    TRANSITION = "TRANSITION"
    EXIT = "EXIT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Transition:
    """A state change between two real samples: it happened in (x_before, x_at]."""

    index: int                 # trace.points index of the first sample in the new state
    x_at: float
    x_before: float | None     # None: state already held at the first sample (censored)


@dataclass(frozen=True)
class BrakeApplication:
    onset: Transition
    release: Transition | None  # None: still braking at the last sample
    peak_pct: float
    peak_index: int
    speed_at_onset_kph: float | None


@dataclass(frozen=True)
class ThrottleLift:
    lift: Transition
    minimum_pct: float
    minimum_index: int
    application: Transition | None  # first rise after the minimum; None if never rises
    full: Transition | None         # full throttle regained; None if not by trace end
    braking_indices: tuple[int, int] | None  # first/last braking sample inside the lift
    end_index: int = 0                       # exclusive end (full regained or next braking)


@dataclass(frozen=True)
class GearChange:
    at: Transition
    from_gear: int
    to_gear: int


@dataclass
class DriverSignals:
    driver_number: int
    xs: list[float]
    full_throttle_pct: float | None
    brake_available: bool
    throttle_available: bool
    gear_available: bool = False
    drs_available: bool = False
    # most frequent value among full-throttle samples (ties -> higher): the
    # car's typical "full" reading - 99 for #55, 100 for #63 in Singapore
    full_throttle_modal_pct: float | None = None
    brake_applications: list[BrakeApplication] = field(default_factory=list)
    throttle_lifts: list[ThrottleLift] = field(default_factory=list)
    gear_changes: list[GearChange] = field(default_factory=list)
    phases: list[Phase] = field(default_factory=list)


def full_throttle_state(throttle_pct: float | None, full_level: float | None) -> bool | None:
    if throttle_pct is None or full_level is None:
        return None
    return throttle_pct >= full_level - THROTTLE_QUANTUM_PCT


def _transition(xs: list[float], i: int, prev_known: bool) -> Transition:
    return Transition(index=i, x_at=xs[i],
                      x_before=xs[i - 1] if i > 0 and prev_known else None)


def detect_signals(trace: LapDistanceTrace) -> DriverSignals:
    pts = [p for p in trace.points if p.normalized_distance is not None]
    if len(pts) != len(trace.points):
        raise ValueError("detect_signals needs a normalized trace (normalize_lap first)")
    xs = [p.normalized_distance for p in pts]
    brake = [p.brake_pct for p in pts]
    thr = [p.throttle_pct for p in pts]
    known_thr = [t for t in thr if t is not None]
    full_level = max(known_thr) if known_thr else None
    sig = DriverSignals(
        driver_number=trace.driver_number, xs=xs, full_throttle_pct=full_level,
        brake_available=any(b is not None for b in brake),
        throttle_available=bool(known_thr),
        gear_available=any(p.gear is not None for p in pts),
        drs_available=any(p.drs is not None for p in pts))

    sig.brake_applications = _brake_applications(pts, xs, brake)
    full = [full_throttle_state(t, full_level) for t in thr]
    counts: dict[float, int] = {}
    for t, f in zip(thr, full):
        if f:
            counts[t] = counts.get(t, 0) + 1
    if counts:
        sig.full_throttle_modal_pct = max(counts, key=lambda v: (counts[v], v))
    sig.throttle_lifts = _throttle_lifts(xs, thr, full, brake)
    sig.gear_changes = _gear_changes(xs, [p.gear for p in pts])
    sig.phases = _phases(len(pts), brake, full, sig.throttle_lifts)
    return sig


def _brake_applications(pts, xs, brake) -> list[BrakeApplication]:
    out: list[BrakeApplication] = []
    i, n = 0, len(pts)
    while i < n:
        if brake[i] is None or brake[i] <= 0:
            i += 1
            continue
        start = i
        while i < n and brake[i] is not None and brake[i] > 0:
            i += 1
        run = range(start, i)
        peak_index = max(run, key=lambda k: (brake[k], -k))  # first sample at the peak
        release = None
        if i < n and brake[i] is not None:  # first sample observed off again
            release = Transition(index=i, x_at=xs[i], x_before=xs[i - 1])
        out.append(BrakeApplication(
            onset=_transition(xs, start, start > 0 and brake[start - 1] is not None),
            release=release, peak_pct=brake[peak_index], peak_index=peak_index,
            speed_at_onset_kph=pts[start].speed_kph))
    return out


def _on(brake, k: int) -> bool:
    return brake[k] is not None and brake[k] > 0


def _throttle_lifts(xs, thr, full, brake) -> list[ThrottleLift]:
    """One lift per braking zone. A non-full run that holds several brake
    applications (throttle never regained full in between - real on the
    Singapore pair: #63 reaches 89 before braking again) is split at every
    brake onset after the first, so a corner's application is never taken
    from the next corner. full stays None when full was never regained."""
    out: list[ThrottleLift] = []
    i, n = 0, len(xs)
    while i < n:
        if full[i] is not False:  # full or unknown
            i += 1
            continue
        start = i
        while i < n and full[i] is False:
            i += 1
        end = i  # exclusive
        onsets = [k for k in range(start, end) if _on(brake, k) and (k == start
                                                                     or not _on(brake, k - 1))]
        bounds = [start] + onsets[1:] + [end]
        for s0, s1 in pairwise(bounds):
            run = range(s0, s1)
            braking = [k for k in run if _on(brake, k)]
            post = [k for k in run if not braking or k > braking[-1]]
            search = post or list(run)
            minimum = min(thr[k] for k in search)
            last_min = max(k for k in search if thr[k] == minimum)
            j = last_min + 1
            application = None
            if (j < s1 or (j == s1 == end and end < n)) and j < n and thr[j] is not None:
                application = Transition(index=j, x_at=xs[j], x_before=xs[last_min])
            regained = None
            if s1 == end and end < n and full[end] is True:
                regained = Transition(index=end, x_at=xs[end], x_before=xs[end - 1])
            lift = (_transition(xs, s0, s0 > 0 and full[s0 - 1] is not None) if s0 == start
                    else Transition(index=s0, x_at=xs[s0], x_before=xs[s0 - 1]))
            out.append(ThrottleLift(
                lift=lift, minimum_pct=minimum, minimum_index=last_min,
                application=application, full=regained,
                braking_indices=(braking[0], braking[-1]) if braking else None,
                end_index=s1))
    return out


def _gear_changes(xs, gears) -> list[GearChange]:
    out: list[GearChange] = []
    for i in range(1, len(gears)):
        g0, g1 = gears[i - 1], gears[i]
        if g0 is not None and g1 is not None and g0 != g1:
            out.append(GearChange(at=Transition(index=i, x_at=xs[i], x_before=xs[i - 1]),
                                  from_gear=int(g0), to_gear=int(g1)))
    return out


def _phases(n, brake, full, lifts: list[ThrottleLift]) -> list[Phase]:
    phases = [Phase.UNKNOWN] * n
    for k in range(n):
        if brake[k] is None or full[k] is None:
            continue
        if brake[k] > 0:
            phases[k] = Phase.BRAKING
        elif full[k]:
            phases[k] = Phase.FULL_THROTTLE
    for lift in lifts:
        end = lift.end_index
        app = lift.application.index if lift.application else end
        last_brake = lift.braking_indices[1] if lift.braking_indices else None
        for k in range(lift.lift.index, end):
            if phases[k] is not Phase.UNKNOWN or brake[k] is None:
                continue
            if last_brake is not None and k < last_brake:
                phases[k] = Phase.LIFT            # before/between braking
            elif k >= app:
                phases[k] = Phase.EXIT
            elif last_brake is not None:
                phases[k] = Phase.TRANSITION      # released, not yet rising
            else:
                phases[k] = Phase.LIFT            # lift without braking
    return phases
