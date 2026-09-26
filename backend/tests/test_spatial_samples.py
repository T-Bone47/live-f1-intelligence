"""Phase 12A Task 6: every location sample classified, never repaired."""

from __future__ import annotations

from datetime import datetime

from spatial_synth import (
    DEFAULT_CARS,
    SID,
    T0,
    Pit,
    at,
    location_row,
    pit_row,
    s_of,
    synth_rows,
    track_xy,
)

from app.analysis.common.models import Confidence
from app.spatial.reference import build_reference, eligible_laps, reference_candidates
from app.spatial.samples import (
    TOL_QUANTILE,
    SampleFlag,
    choose_pit_mode,
    classify_driver,
    derive_tolerance,
    lateral_offsets,
    pit_windows,
)
from app.spatial.source import inputs_from_rows
from app.spatial.timing_lines import measure_lines, nearest_rank

PIT = Pit(2, 3, exit_at_s=185.0)


def _setup(rows):
    inputs = inputs_from_rows(SID, rows)
    ref = build_reference(inputs, reference_candidates(inputs)[0])
    finish = measure_lines(inputs, ref, None)["FINISH"].fraction
    tol, _pct, _n = derive_tolerance(inputs, ref, eligible_laps(inputs, require_coverage=False))
    return inputs, ref, finish, tol


def _at(samples, seconds: float):
    return next(s for s in samples if abs(s.t - T0.timestamp() - seconds) < 1e-6)


def test_tolerance_is_the_p999_of_green_lap_offsets():
    inputs, ref, _finish, tol = _setup(synth_rows())
    green = eligible_laps(inputs, require_coverage=False)
    assert tol == nearest_rank(lateral_offsets(inputs, ref, green), TOL_QUANTILE)
    assert 0 <= tol < 10


def test_exit_pit_mode_is_detected_when_the_window_ends_at_ts():
    inputs, ref, _finish, tol = _setup(synth_rows(pits=(PIT,)))
    result = choose_pit_mode(inputs, ref, tol)
    assert result.mode == "EXIT"
    assert result.share_exit >= 0.9 > result.share_entry
    assert pit_windows(inputs, "EXIT") == [(2, at(165.0).timestamp(), at(185.0).timestamp())]


def test_pit_mode_is_none_when_neither_window_is_off_reference():
    inputs, ref, _finish, tol = _setup(synth_rows(extra=(pit_row(1, 3, at(150.0), 20.0),)))
    assert choose_pit_mode(inputs, ref, tol).mode == "NONE"


def test_pit_lane_samples_keep_xy_but_get_no_fraction():
    inputs, ref, finish, tol = _setup(synth_rows(pits=(PIT,)))
    out = classify_driver(inputs, 2, ref, finish, tol, pit_windows(inputs, "EXIT"))
    lane = [s for s in out if 165.0 <= s.t - T0.timestamp() <= 185.0]
    assert lane and all(s.flag is SampleFlag.PIT_LANE for s in lane)
    assert all(s.fraction is None and s.lap is None and s.confidence is Confidence.HIGH
               for s in lane)


def test_off_reference_garage_samples_get_no_fraction():
    garage = (location_row(1, at(150.1), 500.0, 500.0), location_row(1, at(150.2), 500.0, 500.0))
    inputs, ref, finish, tol = _setup(synth_rows(extra=garage))
    out = classify_driver(inputs, 1, ref, finish, tol, [])
    for sec in (150.1, 150.2):
        s = _at(out, sec)
        assert s.flag is SampleFlag.OFF_REFERENCE and s.fraction is None and (s.x, s.y) == (500.0, 500.0)


def test_on_reference_fraction_is_measured_from_the_finish_line():
    inputs, ref, finish, tol = _setup(synth_rows())
    s = _at(classify_driver(inputs, 1, ref, finish, tol, []), 75.0)   # crossing 1 + 15 s
    assert s.flag is SampleFlag.ON_REFERENCE and s.lap == 2 and s.confidence is Confidence.HIGH
    assert abs(s.fraction - 0.25) < 1e-8


def test_samples_outside_timed_laps_are_low_confidence_without_a_lap():
    inputs, ref, finish, tol = _setup(synth_rows())
    early = [s for s in classify_driver(inputs, 1, ref, finish, tol, [])
             if s.t < T0.timestamp()]
    assert early and all(s.lap is None and s.confidence is Confidence.LOW
                         and s.fraction is not None for s in early)


def test_a_backward_jump_is_withheld_not_repaired():
    car = DEFAULT_CARS[0]
    moved = location_row(1, at(90.0), *track_xy(s_of(car, 90.0) - 100.0))
    rows = [r for r in synth_rows()
            if not (r[1]["type"] == "TelemetryLocationSample" and r[1]["driver_number"] == 1
                    and datetime.fromisoformat(r[1]["ts"]) == at(90.0))] + [moved]
    inputs, ref, finish, tol = _setup(rows)
    s = _at(classify_driver(inputs, 1, ref, finish, tol, []), 90.0)
    assert s.fraction is None and s.confidence is Confidence.NONE
    assert s.flag is SampleFlag.ON_REFERENCE
