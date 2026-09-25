"""Phase 10.3: position-based lap alignment (self-referential centerline).

Synthetic geometry on purpose: a 400-unit square path gives exact,
hand-checkable arc lengths. Units are arbitrary (like OpenF1's x/y), which
is the point - everything here works in fractions of the reference path.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.analysis.common.models import Confidence, LapClass
from app.analysis.lap_comparison import compare_driver_laps, compare_traces, delta_at
from app.analysis.lap_distance import build_lap_distance_trace, normalize_lap, resample_common_grid
from app.analysis.track_geometry import (
    build_centerline,
    build_position_distance_trace,
    project_positions,
)
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Lap, Provenance, TelemetryCarSample, TelemetryLocationSample

PROV = Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.B)
T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
SID = "test:geom"


def square_xy(s: float) -> tuple[float, float]:
    """Point at arc length s along a 100x100 square starting at (0,0), counter-clockwise."""
    s = s % 400.0
    if s < 100:
        return (s, 0.0)
    if s < 200:
        return (100.0, s - 100)
    if s < 300:
        return (300 - s, 100.0)
    return (0.0, 400 - s)


def loc(t: float, x: float | None, y: float | None, driver: int = 1) -> TelemetryLocationSample:
    return TelemetryLocationSample(session_id=SID, driver_number=driver,
                                   ts=T0 + timedelta(seconds=t), x=x, y=y, z=0.0, provenance=PROV)


def car(t: float, speed: int, driver: int = 1) -> TelemetryCarSample:
    return TelemetryCarSample(session_id=SID, driver_number=driver,
                              ts=T0 + timedelta(seconds=t), speed_kph=speed, provenance=PROV)


def ref_path(n: int = 400):
    """A full lap of the square, 1 unit per sample, 0.1s apart."""
    return [loc(i * 0.1, *square_xy(float(i))) for i in range(n + 1)]


# --- centerline -------------------------------------------------------------

def test_centerline_arc_length_is_exact():
    cl = build_centerline(ref_path())
    assert cl.total_length == pytest.approx(400.0)


def test_centerline_drops_missing_and_repeated_points():
    samples = [loc(0, 0, 0), loc(0.1, None, None), loc(0.2, 0, 0), loc(0.3, 50, 0),
               loc(0.4, 100, 0), loc(0.5, 100, 50)]
    cl = build_centerline(samples)
    assert len(cl.points) == 4  # (0,0) (50,0) (100,0) (100,50)
    assert cl.total_length == pytest.approx(150.0)


def test_centerline_needs_three_distinct_points():
    with pytest.raises(ValueError):
        build_centerline([loc(0, 0, 0), loc(0.1, 0, 0), loc(0.2, 5, 0)])


# --- projection -------------------------------------------------------------

def test_projection_on_and_off_the_path_is_exact():
    cl = build_centerline(ref_path())
    on = cl.project(150.0 - 50.0, 50.0)          # (100, 50): s = 150 on the 2nd side
    assert on.s == pytest.approx(150.0) and on.offset == pytest.approx(0.0)
    off = cl.project(40.0, -3.0)                 # 3 units outside the 1st side
    assert off.s == pytest.approx(40.0) and off.offset == pytest.approx(3.0)


def test_windowed_search_matches_global_search():
    cl = build_centerline(ref_path())
    hinted, prev = [], None
    for s in range(0, 400, 7):
        p = cl.project(*square_xy(s + 0.5), hint=prev)
        hinted.append(p.s)
        prev = p.segment
    assert hinted == pytest.approx([cl.project(*square_xy(s + 0.5)).s for s in range(0, 400, 7)])


def test_projection_is_fast_enough_for_real_laps():
    """Real laps: ~340 location samples; stress with a 4000-point path x 4000 projections."""
    import math
    dense = [loc(i * 0.01, 1000 * math.cos(i * 2 * math.pi / 4000),
                 1000 * math.sin(i * 2 * math.pi / 4000)) for i in range(4001)]
    cl = build_centerline(dense)
    moving = dense[::1]
    t = time.perf_counter()
    project_positions(cl, moving, lap_duration_s=40.0)
    assert time.perf_counter() - t < 2.0  # windowed search: linear, not quadratic


# --- unwrapping and outliers ------------------------------------------------

def test_sample_just_before_the_line_is_negative_not_end_of_lap():
    cl = build_centerline(ref_path())
    pts = project_positions(cl, [loc(0, *square_xy(398.0)), loc(0.4, *square_xy(2.0)),
                                 loc(0.8, *square_xy(6.0))], lap_duration_s=40.0)
    assert [round(p.fraction, 4) for p in pts] == [-0.005, 0.005, 0.015]


def test_small_backward_jitter_is_held_and_downgraded():
    cl = build_centerline(ref_path())
    # 10 units/s = the 40 s lap's own mean rate (the rate guard checks this)
    pts = project_positions(cl, [loc(1.0, *square_xy(10)), loc(2.0, *square_xy(20)),
                                 loc(2.1, *square_xy(19.8)), loc(3.0, *square_xy(30))],
                            lap_duration_s=40.0)
    assert [p.confidence for p in pts] == [Confidence.HIGH, Confidence.HIGH,
                                           Confidence.MEDIUM, Confidence.HIGH]
    assert pts[2].fraction == pytest.approx(20 / 400)   # held, never goes backwards
    assert pts[2].confidence == Confidence.MEDIUM
    assert [p.fraction for p in pts] == sorted(p.fraction for p in pts)


def test_large_backward_jump_is_an_outlier():
    cl = build_centerline(ref_path())
    pts = project_positions(cl, [loc(10.0, *square_xy(100)), loc(11.0, *square_xy(110)),
                                 loc(11.1, *square_xy(60)), loc(12.0, *square_xy(120))],
                            lap_duration_s=40.0)
    assert [p.confidence for p in pts] == [Confidence.HIGH, Confidence.HIGH,
                                           Confidence.NONE, Confidence.HIGH]


def test_impossible_forward_jump_is_an_outlier():
    # lap mean progress = 1/40 per second; 0.25 of a lap in 0.1s is 100x that.
    cl = build_centerline(ref_path())
    pts = project_positions(cl, [loc(0, *square_xy(10)), loc(0.1, *square_xy(110)),
                                 loc(0.2, *square_xy(12))], lap_duration_s=40.0)
    # the jump is rejected; continuity resumes from the last ACCEPTED point
    assert [p.confidence for p in pts] == [Confidence.HIGH, Confidence.NONE, Confidence.HIGH]


def test_missing_xy_is_skipped_not_guessed():
    cl = build_centerline(ref_path())
    pts = project_positions(cl, [loc(0, *square_xy(10)), loc(0.1, None, None),
                                 loc(0.2, *square_xy(12))], lap_duration_s=40.0)
    assert len(pts) == 2


# --- position-distance traces -------------------------------------------------

def _lap(driver: int, duration: float, start: float = 0.0) -> Lap:
    return Lap(session_id=SID, driver_number=driver, lap_number=1,
               started_at=T0 + timedelta(seconds=start), duration_s=duration, provenance=PROV)


def test_trace_distance_comes_from_position_and_time_starts_at_the_lap_start():
    cl = build_centerline(ref_path())
    lap = _lap(1, 40.0)
    # car at 10 units/s; location every 1s from t=0.5; car samples every 0.5s from t=0.25
    locs = [loc(0.5 + k, *square_xy(10 * (0.5 + k))) for k in range(39)]
    cars = [car(0.25 + 0.5 * k, 36) for k in range(79)]
    trace = build_position_distance_trace(lap, cars, locs, cl, lap_length_m=4000.0)
    assert trace.time_origin == lap.started_at
    # car sample at t=1.25 sits between location samples at 1.0 (s=10) and... t=0.5 (s=5), t=1.5 (s=15)
    p = next(pt for pt in trace.points if abs((pt.ts - T0).total_seconds() - 1.25) < 1e-9)
    assert p.distance_m == pytest.approx(12.5 / 400 * 4000.0)
    # car samples outside location coverage (t=0.25, t>38.5) are excluded, not extrapolated
    ts = [(pt.ts - T0).total_seconds() for pt in trace.points]
    assert min(ts) >= 0.5 and max(ts) <= 38.5


def test_resample_measures_elapsed_from_time_origin_when_set():
    cl = build_centerline(ref_path())
    lap = _lap(1, 40.0)
    locs = [loc(0.5 + k, *square_xy(10 * (0.5 + k))) for k in range(39)]
    cars = [car(0.5 + 0.5 * k, 36) for k in range(77)]
    trace = normalize_lap(build_position_distance_trace(lap, cars, locs, cl, lap_length_m=4000.0), 4000.0)
    series = resample_common_grid(trace, step=0.05)
    i = series.grid_x.index(0.25)          # s = 100 units -> reached at t = 10.0s after lap start
    assert series.elapsed_s[i] == pytest.approx(10.0)


def test_position_alignment_survives_a_speed_channel_that_under_reads():
    """The reason Phase 10.3 exists. Both cars drive the identical profile,
    so the true delta is 0 everywhere. B's speed channel reads 2% low:
    speed integration then misplaces B, position alignment does not."""
    cl = build_centerline(ref_path())
    la, lb = _lap(1, 40.0), _lap(2, 40.0, start=100.0)

    def drive(driver, t_off, speed_kph):
        locs = [loc(t_off + 0.25 * k, *square_xy(10 * 0.25 * k), driver) for k in range(161)]
        cars = [car(t_off + 0.25 * k, speed_kph, driver) for k in range(161)]
        return locs, cars

    loc_a, car_a = drive(1, 0.0, 36)    # 36 km/h = 10 units/s: the true speed
    loc_b, car_b = drive(2, 100.0, 35)  # B's (integer) speed channel reads 2.8% low

    speed_cmp = compare_driver_laps(la, car_a, LapClass.REPRESENTATIVE, lb, car_b,
                                    LapClass.REPRESENTATIVE, lap_length_m=400.0, step=0.05)
    pos_cmp = compare_traces(
        build_position_distance_trace(la, car_a, loc_a, cl, 400.0, LapClass.REPRESENTATIVE),
        build_position_distance_trace(lb, car_b, loc_b, cl, 400.0, LapClass.REPRESENTATIVE),
        lap_length_m=400.0, step=0.05)

    assert abs(delta_at(speed_cmp, 0.5)) > 0.5            # 2.8% under-read -> ~0.57s fake loss
    for x in (0.25, 0.5, 0.75):
        assert delta_at(pos_cmp, x) == pytest.approx(0.0, abs=1e-6)


def test_speed_traces_keep_their_existing_time_origin_behaviour():
    lap = _lap(1, 10.0)
    trace = build_lap_distance_trace(lap, [car(0.3 + k, 360) for k in range(10)],
                                     LapClass.REPRESENTATIVE)
    assert trace.time_origin is None  # unchanged 10.1B semantics: elapsed from first sample


def test_car_samples_inside_a_location_gap_are_downgraded():
    """Position is interpolated across a hole in the location feed; samples
    inside a hole wider than MAX_GAP_S must not claim HIGH confidence."""
    cl = build_centerline(ref_path())
    lap = _lap(1, 40.0)
    locs = [loc(t, *square_xy(10 * t)) for t in [k * 0.5 for k in range(81)] if not 10.0 < t < 13.5]
    cars = [car(0.25 * k, 36) for k in range(161)]
    trace = build_position_distance_trace(lap, cars, locs, cl, 400.0, LapClass.REPRESENTATIVE)
    in_hole = [p for p in trace.points if 10.0 < (p.ts - T0).total_seconds() < 13.5]
    elsewhere = [p for p in trace.points if (p.ts - T0).total_seconds() < 9.0]
    assert in_hole and all(p.confidence == Confidence.LOW for p in in_hole)
    assert all(p.confidence == Confidence.HIGH for p in elsewhere)
    assert trace.confidence != Confidence.HIGH
