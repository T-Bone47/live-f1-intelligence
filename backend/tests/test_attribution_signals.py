"""Phase 10.4 per-driver control-input detection (synthetic ground truth).

Detectors read the REAL samples of a 10.1B trace (never the interpolated
grid), and locate every state change between two real samples: the change
happened in (x_before, x_at]. These tests pin those definitions.
"""

from __future__ import annotations

import pytest
from synthetic_lap import Profile, make_lap, two_corner_profile

from app.analysis.attribution_signals import Phase, detect_signals, full_throttle_state
from app.analysis.lap_distance import build_lap_distance_trace, normalize_lap

L = 2000.0


def _signals(profile, driver=1, **kw):
    lap, samples = make_lap(profile, driver, **kw)
    trace = normalize_lap(build_lap_distance_trace(lap, samples), profile.length_m)
    return trace, detect_signals(trace)


def test_brake_onset_peak_release_are_located_between_real_samples():
    trace, sig = _signals(two_corner_profile())
    assert len(sig.brake_applications) == 2
    b = sig.brake_applications[0]
    pts = trace.points
    assert pts[b.onset.index].brake_pct == 100 and pts[b.onset.index - 1].brake_pct == 0
    assert b.onset.x_before == pts[b.onset.index - 1].normalized_distance
    assert b.onset.x_at == pts[b.onset.index].normalized_distance
    assert pts[b.release.index].brake_pct == 0 and pts[b.release.index - 1].brake_pct == 100
    assert b.peak_pct == 100.0
    assert b.speed_at_onset_kph == pts[b.onset.index].speed_kph
    # true onset (500 m) lies in the bracket, up to trapezoid integration error
    assert b.onset.x_before * L - 3 < 500 <= b.onset.x_at * L + 3


def test_later_braking_moves_the_onset_by_the_known_offset():
    base = two_corner_profile()
    late = two_corner_profile(
        speed_knots=[(0, 280), (520, 300), (600, 100), (650, 100), (900, 290),
                     (1300, 300), (1380, 150), (1420, 150), (1650, 290), (2000, 295)],
        brake=[(520, 600), (1300, 1380)])
    _, a = _signals(base)
    _, b = _signals(late)
    offset_m = (b.brake_applications[0].onset.x_at - a.brake_applications[0].onset.x_at) * L
    spacing_m = 300 / 3.6 / 3.7  # one sample interval at ~300 kph
    assert abs(offset_m - 20.0) <= spacing_m + 3


def test_identical_braking_gives_identical_onsets():
    _, a = _signals(two_corner_profile(), driver=1)
    _, b = _signals(two_corner_profile(), driver=2)
    assert [x.onset.x_at for x in a.brake_applications] == [
        x.onset.x_at for x in b.brake_applications]


def test_throttle_lift_application_and_full():
    trace, sig = _signals(two_corner_profile())
    lift = sig.throttle_lifts[0]
    pts = trace.points
    assert pts[lift.lift.index - 1].throttle_pct >= sig.full_throttle_pct - 1
    assert pts[lift.lift.index].throttle_pct < sig.full_throttle_pct - 1
    assert lift.minimum_pct == 0
    app = lift.application
    assert pts[app.index].throttle_pct > 0 and pts[app.index - 1].throttle_pct == 0
    # application comes after the brake release, full after application
    assert app.x_at > sig.brake_applications[0].release.x_at - 1e-12
    assert lift.full.x_at > app.x_at


def test_delayed_throttle_application_is_detected():
    late = two_corner_profile(throttle_knots=[
        (0, 100), (495, 100), (500, 0), (660, 0), (680, 30), (740, 100), (1295, 100),
        (1300, 0), (1400, 0), (1420, 40), (1500, 100), (2000, 100)])
    _, a = _signals(two_corner_profile())
    _, b = _signals(late)
    delay_m = (b.throttle_lifts[0].application.x_at - a.throttle_lifts[0].application.x_at) * L
    assert 40 - 30 <= delay_m <= 40 + 30  # 40 m later, within one slow-speed sample


def test_full_throttle_level_is_per_car_not_a_fixed_100():
    # Real feed: #55 sits at 99 on straights, #63 at 100 (Singapore fixture).
    capped = two_corner_profile(throttle_knots=[
        (0, 99), (495, 99), (500, 0), (620, 0), (640, 30), (720, 99), (1295, 99),
        (1300, 0), (1400, 0), (1420, 40), (1500, 99), (2000, 99)])
    _, sig = _signals(capped)
    assert sig.full_throttle_pct == 99
    assert full_throttle_state(99.0, sig.full_throttle_pct) is True
    assert full_throttle_state(98.0, sig.full_throttle_pct) is True   # one quantum below
    assert full_throttle_state(97.0, sig.full_throttle_pct) is False
    assert Phase.FULL_THROTTLE in sig.phases


def test_phases_follow_the_control_inputs():
    trace, sig = _signals(two_corner_profile())
    by_pos = {round(p.distance_m): ph for p, ph in zip(trace.points, sig.phases)}

    def phase_near(m):
        k = min(by_pos, key=lambda d: abs(d - m))
        return by_pos[k]

    assert phase_near(300) is Phase.FULL_THROTTLE
    assert phase_near(550) is Phase.BRAKING
    assert phase_near(612) is Phase.TRANSITION   # released, throttle still 0
    assert phase_near(690) is Phase.EXIT         # applying, not yet full
    assert Phase.UNKNOWN not in sig.phases
    assert "APEX" not in {p.value for p in Phase}  # no geometry -> never claimed


def test_gear_changes_are_integers_never_blended():
    _, sig = _signals(two_corner_profile())
    assert all(isinstance(g.from_gear, int) and isinstance(g.to_gear, int)
               for g in sig.gear_changes)
    assert sig.gear_changes[0].from_gear == 8
    assert min(g.to_gear for g in sig.gear_changes) == 3


def test_missing_brake_channel_is_unavailable_not_zero():
    lap, samples = make_lap(two_corner_profile(), 1)
    samples = [s.model_copy(update={"brake_pct": None}) for s in samples]
    trace = normalize_lap(build_lap_distance_trace(lap, samples), L)
    sig = detect_signals(trace)
    assert sig.brake_available is False
    assert sig.brake_applications == []
    assert set(sig.phases) == {Phase.UNKNOWN}


def test_state_held_from_trace_start_is_censored():
    # braking already on at the first sample: onset NOT observable
    prof = Profile(length_m=600.0, speed_knots=[(0, 200), (100, 100), (600, 250)],
                   brake=[(0, 100)], throttle_knots=[(0, 0), (150, 0), (300, 100), (600, 100)])
    _, sig = _signals(prof)
    assert sig.brake_applications[0].onset.x_before is None


@pytest.mark.parametrize("hz", [3.7, 4.0])
def test_detection_is_deterministic(hz):
    _, a = _signals(two_corner_profile(), hz=hz)
    _, b = _signals(two_corner_profile(), hz=hz)
    assert a == b


def test_a_lift_never_spans_two_braking_zones():
    # Regression (real Singapore pair, #63 near 2,660 m): throttle rises to 89
    # but never reaches full before braking again. The two corners must be two
    # lifts - otherwise corner 1's "application" is taken from corner 2.
    prof = two_corner_profile(
        speed_knots=[(0, 280), (500, 300), (600, 100), (650, 100), (800, 200), (850, 200),
                     (900, 120), (940, 120), (1200, 290), (2000, 295)],
        brake=[(500, 600), (850, 900)],
        throttle_knots=[(0, 100), (495, 100), (500, 0), (620, 0), (640, 30), (760, 80),
                        (845, 80), (850, 0), (920, 0), (940, 40), (1100, 100), (2000, 100)])
    _trace, sig = _signals(prof)
    assert len(sig.throttle_lifts) == 2
    first, second = sig.throttle_lifts
    assert first.full is None                      # full never regained before corner 2
    assert first.application.x_at * L < 700        # corner 1's own exit, not corner 2's
    assert second.application.x_at * L > 900
    for lift in sig.throttle_lifts:
        onsets = [b for b in sig.brake_applications
                  if lift.lift.index <= b.onset.index < lift.end_index]
        assert len(onsets) <= 1
    assert sig.phases[first.application.index] is Phase.EXIT
