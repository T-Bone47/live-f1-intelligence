"""Phase 10.2: engineering delta analysis tests.

Expected values are derived by hand from piecewise-constant speed profiles
(derivations in each test), not copied from the implementation's output.
Speed changes use a duplicate timestamp at the transition, which the 10.1B
engine integrates as exactly zero distance, so every distance - and
therefore every delta - is exact.

Lap length 1000m throughout. Speeds: 360 km/h = 100 m/s, 240 km/h =
66.67 m/s, 150 km/h = 41.67 m/s.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.common.models import Confidence, LapClass
from app.analysis.delta_analysis import (
    SIGN_CONVENTION,
    DeltaSample,
    SegmentKind,
    analyze_delta,
    segment_delta_curve,
)
from app.analysis.lap_comparison import compare_driver_laps, delta_at
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Lap, Provenance, TelemetryCarSample
from app.providers.openf1.mapping import to_car_sample

PROV = Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.A)
BASE = datetime(2026, 1, 1, tzinfo=UTC)
SESSION = "test:session"


def _piecewise(driver: int, segments: list[tuple[int, float, int | None]]):
    """segments: (duration_s, speed_kph, gear). Returns (samples, lap)."""
    samples, t = [], 0
    for dur, speed, gear in segments:
        for k in range(dur + 1):
            samples.append(TelemetryCarSample(
                session_id=SESSION, driver_number=driver,
                ts=BASE + timedelta(seconds=t + k), speed_kph=speed, gear=gear,
                provenance=PROV))
        t += dur
    lap = Lap(session_id=SESSION, driver_number=driver, lap_number=1,
              started_at=BASE, duration_s=float(t), provenance=PROV)
    return samples, lap


def _compare(segs_a, segs_b, step=0.1):
    sa, la = _piecewise(1, segs_a)
    sb, lb = _piecewise(2, segs_b)
    return compare_driver_laps(la, sa, LapClass.REPRESENTATIVE,
                                lb, sb, LapClass.REPRESENTATIVE,
                                lap_length_m=1000.0, step=step)


# A: 500m @100 m/s (5s) then 500m @41.67 m/s (12s) = 17s.  B: 1000m @66.67 m/s = 15s.
# elapsed_A = 10x (x<=0.5), 5 + 24(x-0.5) after; elapsed_B = 15x.
# delta = -5x for x<=0.5 (-2.5 at 0.5); 9x - 7 after (+2.0 at the finish).
FAST_THEN_SLOW = [(5, 360.0, 7), (12, 150.0, 5)]
CONSTANT_B = [(15, 240.0, 6)]


def test_delta_curve_matches_hand_derived_values():
    an = analyze_delta(_compare(FAST_THEN_SLOW, CONSTANT_B))
    by_x = {round(s.x, 6): s.delta_t_s for s in an.samples}
    assert by_x[0.0] == pytest.approx(0.0, abs=1e-6)
    assert by_x[0.2] == pytest.approx(-1.0, abs=1e-6)   # -5 * 0.2
    assert by_x[0.5] == pytest.approx(-2.5, abs=1e-6)
    assert by_x[0.8] == pytest.approx(0.2, abs=1e-6)    # 9*0.8 - 7
    assert by_x[1.0] == pytest.approx(2.0, abs=1e-6)
    assert an.delta_at_start_s == pytest.approx(0.0, abs=1e-6)
    assert an.delta_at_finish_s == pytest.approx(2.0, abs=1e-6)


def test_max_gain_and_max_loss_with_their_distances():
    an = analyze_delta(_compare(FAST_THEN_SLOW, CONSTANT_B))
    assert an.max_gain_s == pytest.approx(-2.5, abs=1e-6)
    assert an.max_gain_x == pytest.approx(0.5)
    assert an.max_loss_s == pytest.approx(2.0, abs=1e-6)
    assert an.max_loss_x == pytest.approx(1.0)


def test_gaining_then_losing_segmentation():
    an = analyze_delta(_compare(FAST_THEN_SLOW, CONSTANT_B))
    kinds = [s.kind for s in an.segments]
    assert kinds == [SegmentKind.GAINING, SegmentKind.LOSING]
    gain, loss = an.segments
    assert (gain.x_start, gain.x_end) == pytest.approx((0.0, 0.5))
    assert gain.time_change_s == pytest.approx(-2.5, abs=1e-6)
    assert (loss.x_start, loss.x_end) == pytest.approx((0.5, 1.0))
    assert loss.time_change_s == pytest.approx(4.5, abs=1e-6)  # -2.5 -> +2.0
    # segment changes must sum to the whole-lap delta change
    assert sum(s.time_change_s for s in an.segments) == pytest.approx(2.0, abs=1e-6)


def test_losing_then_recovering_when_gaining_while_behind():
    # A: 500m @41.67 (12s) then 500m @100 (5s). delta = 9x to 0.5 (+4.5),
    # then 7 - 5x (+2.0 at finish): gaining time, but still behind -> RECOVERING.
    an = analyze_delta(_compare([(12, 150.0, 5), (5, 360.0, 7)], CONSTANT_B))
    assert [s.kind for s in an.segments] == [SegmentKind.LOSING, SegmentKind.RECOVERING]
    assert an.segments[1].delta_start_s == pytest.approx(4.5, abs=1e-6)
    assert an.segments[1].time_change_s == pytest.approx(-2.5, abs=1e-6)
    assert an.max_gain_s is None  # A never led, so there is no gain to report
    assert an.max_loss_s == pytest.approx(4.5, abs=1e-6)


def test_identical_laps_are_one_stable_segment_with_no_gain_or_loss():
    an = analyze_delta(_compare(CONSTANT_B, CONSTANT_B))
    assert [s.kind for s in an.segments] == [SegmentKind.STABLE]
    assert an.max_gain_s is None and an.max_loss_s is None


def test_missing_coverage_is_a_no_data_segment_not_a_guess():
    # B only covers 600m of the 1000m lap.
    an = analyze_delta(_compare([(10, 360.0, 7)], [(6, 360.0, 7)]))
    assert [s.kind for s in an.segments] == [SegmentKind.STABLE, SegmentKind.NO_DATA]
    no_data = an.segments[1]
    assert no_data.x_start == pytest.approx(0.6)
    assert no_data.x_end == pytest.approx(1.0)
    assert no_data.time_change_s is None
    assert no_data.confidence == Confidence.NONE
    assert an.delta_at_finish_s is None


def test_sub_resolution_wiggle_is_stable_real_change_is_not():
    def s(x, d):
        return DeltaSample(x=x, delta_t_s=d, confidence=Confidence.HIGH)

    wiggle = [s(0.0, 0.0), s(0.1, 0.0002), s(0.2, -0.0001), s(0.3, 0.0003), s(0.4, 0.0)]
    assert [g.kind for g in segment_delta_curve(wiggle)] == [SegmentKind.STABLE]

    real = [s(0.0, 0.0), s(0.1, 0.0002), s(0.2, -0.0001), s(0.3, 1.0)]
    segs = segment_delta_curve(real)
    assert [g.kind for g in segs] == [SegmentKind.STABLE, SegmentKind.LOSING]
    assert segs[1].time_change_s == pytest.approx(1.0001)


def test_telemetry_differences_per_segment():
    an = analyze_delta(_compare(FAST_THEN_SLOW, CONSTANT_B))
    at_02 = next(s for s in an.samples if round(s.x, 6) == 0.2)
    assert at_02.continuous_delta["speed_kph"] == pytest.approx(360.0 - 240.0)
    # losing half: A at 150 vs B at 240 at every grid point, boundary included
    assert an.segments[1].mean_continuous_delta["speed_kph"] == pytest.approx(-90.0)


def test_discrete_fields_are_compared_never_subtracted():
    an = analyze_delta(_compare(FAST_THEN_SLOW, CONSTANT_B))
    for s in an.samples:
        assert "gear" not in s.continuous_delta and "drs" not in s.continuous_delta
    at_02 = next(s for s in an.samples if round(s.x, 6) == 0.2)
    assert (at_02.a["gear"], at_02.b["gear"]) == (7, 6)  # real integers, not 6.5 or +1
    assert at_02.discrete_differs["gear"] is True
    # losing half: A in 5th throughout vs B in 6th -> gear differs at every point
    assert an.segments[1].discrete_difference_fraction["gear"] == pytest.approx(1.0)


def test_sign_convention_is_inherited_not_redefined():
    cmp = _compare(FAST_THEN_SLOW, CONSTANT_B)
    an = analyze_delta(cmp)
    assert SIGN_CONVENTION.startswith("delta_t = elapsed_A - elapsed_B")
    for s in an.samples:
        assert s.delta_t_s == delta_at(cmp, s.x)  # identical to the 10.1B/10.1C value


def test_repeated_analysis_is_deterministic():
    a1 = analyze_delta(_compare(FAST_THEN_SLOW, CONSTANT_B, step=0.01))
    a2 = analyze_delta(_compare(FAST_THEN_SLOW, CONSTANT_B, step=0.01))
    assert [s.delta_t_s for s in a1.samples] == [s.delta_t_s for s in a2.samples]
    assert [(g.kind, g.start_index, g.end_index) for g in a1.segments] == \
           [(g.kind, g.start_index, g.end_index) for g in a2.segments]


def test_real_openf1_telemetry_claims_no_gain_or_loss_it_cannot_support():
    """Driver 55's real telemetry (Phase 10.1A fixture, via the real mapper)
    is a stationary warm-up: it covers only x=0. Against any moving driver,
    the honest analysis is one NO_DATA region and no gain/loss claims."""
    raw = (Path(__file__).parent.parent.parent / "scripts" / "fixtures"
           / "real-openf1-9159" / "raw_car_data_source.json")
    rows = sorted(json.loads(raw.read_text()), key=lambda r: r["date"])
    real = [to_car_sample(r, "openf1:9159")
            for r in rows if r["date"].startswith("2023-09-15T12:48")]
    start, end = real[0].ts, real[-1].ts
    dur = (end - start).total_seconds()
    lap_a = Lap(session_id="openf1:9159", driver_number=55, lap_number=1,
                started_at=start, duration_s=dur, provenance=PROV)
    lap_b = Lap(session_id="openf1:9159", driver_number=99, lap_number=1,
                started_at=start, duration_s=dur, provenance=PROV)
    samples_b = [TelemetryCarSample(session_id="openf1:9159", driver_number=99,
                                     ts=start + timedelta(seconds=t), speed_kph=36.0,
                                     provenance=PROV) for t in range(int(dur) + 1)]
    cmp = compare_driver_laps(lap_a, real, LapClass.REPRESENTATIVE,
                               lap_b, samples_b, LapClass.REPRESENTATIVE,
                               lap_length_m=100.0, step=0.1)
    an = analyze_delta(cmp)
    assert [s.kind for s in an.segments] == [SegmentKind.NO_DATA]
    assert an.max_gain_s is None and an.max_loss_s is None
    assert an.delta_at_finish_s is None
