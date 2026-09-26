"""Phase 12A Task 7: the state of every car at time t, and driver traces."""

from __future__ import annotations

import math
import random
from datetime import datetime

from spatial_synth import FINISH_S, LENGTH, SID, T0, Car, Pit, synth_rows, track_xy

from app.spatial.reference import build_reference, eligible_laps, reference_candidates
from app.spatial.samples import classify_driver, derive_tolerance, pit_windows
from app.spatial.source import inputs_from_rows
from app.spatial.state import SpatialIndex, state_at, trace, track_from_samples
from app.spatial.timing_lines import circular_diff, measure_lines

EXACT = 1e-4  # epoch-double precision ruling (ledger, Task 2)


def _params(inputs):
    ref = build_reference(inputs, reference_candidates(inputs)[0])
    finish = measure_lines(inputs, ref, None)["FINISH"].fraction
    tol, _p, _n = derive_tolerance(inputs, ref, eligible_laps(inputs, require_coverage=False))
    return ref, finish, tol


def _index(inputs, params=None, windows=()):
    ref, finish, tol = params or _params(inputs)
    tracks = {d: track_from_samples(classify_driver(inputs, d, ref, finish, tol, list(windows)))
              for d in inputs.samples}
    return SpatialIndex(session_id=SID, track_id="trk1_test", ref_points=ref.points,
                        finish_fraction=finish, lap_length_m=4000.0, tracks=tracks)


def _t(seconds: float) -> float:
    return T0.timestamp() + seconds


def _entry(index, driver: int, seconds: float) -> dict:
    return next(e for e in state_at(index, _t(seconds)) if e["driver_number"] == driver)


def test_state_at_a_sample_time_equals_that_sample():
    index = _index(inputs_from_rows(SID, synth_rows()))
    rng = random.Random(12)
    for _ in range(200):
        d = rng.choice(sorted(index.tracks))
        trk = index.tracks[d]
        i = rng.randrange(len(trk.t))
        e = next(e for e in state_at(index, trk.t[i]) if e["driver_number"] == d)
        assert e["status"] == "POSITIONED" and e["bracket"]["gap_s"] == 0.0
        frac = trk.fraction[i]
        assert (e["reference_fraction"] == frac) or (math.isnan(frac) and e["reference_fraction"] is None)
        assert abs(e["x"] - trk.x[i]) < 1e-6 and abs(e["y"] - trk.y[i]) < 1e-6


def test_between_samples_the_fraction_is_interpolated_on_the_reference():
    e = _entry(_index(inputs_from_rows(SID, synth_rows())), 1, 75.1)   # crossing 1 + 15.1 s
    assert e["status"] == "POSITIONED" and e["flag"] == "ON_REFERENCE" and e["lap_number"] == 2
    assert abs(e["reference_fraction"] - 15.1 / 60) < 1e-8
    assert abs(e["distance_m"] - 4000.0 * 15.1 / 60) < EXACT
    x, y = track_xy(FINISH_S + 15.1 * LENGTH / 60)
    assert abs(e["x"] - x) < EXACT and abs(e["y"] - y) < EXACT


def test_interpolation_unwraps_across_the_finish_line():
    # car 2 samples at 121.85 (lap 2, just before the line) and 122.1 (lap 3)
    e = _entry(_index(inputs_from_rows(SID, synth_rows())), 2, 122.05)
    assert e["lap_number"] == 3
    assert abs(circular_diff(e["reference_fraction"], 0.05 / 60)) < 1e-8


def test_gap_over_2_s_is_stale_with_age_and_never_interpolated():
    rows = [r for r in synth_rows()
            if not (r[1]["type"] == "TelemetryLocationSample" and r[1]["driver_number"] == 1
                    and 200.0 < datetime.fromisoformat(r[1]["ts"]).timestamp() - T0.timestamp() < 203.0)]
    index = _index(inputs_from_rows(SID, rows))
    e = _entry(index, 1, 201.5)
    assert e["status"] == "STALE" and e["confidence"] == "LOW"
    assert abs(e["age_s"] - 1.5) < 1e-6 and e["bracket"]["gap_s"] > 2.0
    x, y = track_xy(FINISH_S + 200.0 * LENGTH / 60)        # the 200.0 s sample, not interpolated
    assert abs(e["x"] - x) < EXACT and abs(e["y"] - y) < EXACT


def test_a_retired_car_has_no_coverage_after_its_last_sample():
    cars = (Car(1), Car(2, 2.0, sample_phase_s=0.1), Car(3, 4.0, sample_phase_s=0.2, last_sample_s=130.0))
    e = _entry(_index(inputs_from_rows(SID, synth_rows(cars=cars))), 3, 200.0)
    assert e["status"] == "NO_COVERAGE"
    assert all(e[k] is None for k in ("flag", "confidence", "x", "y", "reference_fraction",
                                      "distance_m", "lap_number", "bracket", "age_s"))


def test_other_drivers_rows_never_change_a_drivers_state():
    full = inputs_from_rows(SID, synth_rows())
    params = _params(full)
    without_2 = inputs_from_rows(SID, synth_rows(cars=(Car(1), Car(3, 4.0, sample_phase_s=0.2))))
    a, b = _index(full, params), _index(without_2, params)
    rng = random.Random(3)
    for _ in range(100):
        t = _t(rng.uniform(-10.0, 380.0))
        assert state_at(a, t)[0] == state_at(b, t)[0]   # driver 1 sorts first in both


def test_trace_returns_the_raw_classified_samples_in_order():
    index = _index(inputs_from_rows(SID, synth_rows()))
    out = trace(index, 1, _t(60.0), _t(70.0))
    assert len(out) == 41 and [s["ts"] for s in out] == sorted(s["ts"] for s in out)
    assert set(out[0]) == {"ts", "x", "y", "flag", "reference_fraction", "distance_m", "sector",
                           "lap_number", "confidence"}
    assert out[0]["ts"] == "2026-01-01T12:01:00+00:00"


def test_pit_lane_state_has_xy_but_no_fraction():
    inputs = inputs_from_rows(SID, synth_rows(pits=(Pit(2, 3, exit_at_s=185.0),)))
    e = _entry(_index(inputs, windows=pit_windows(inputs, "EXIT")), 2, 175.05)
    assert e["status"] == "POSITIONED" and e["flag"] == "PIT_LANE"
    assert e["reference_fraction"] is None and e["distance_m"] is None and e["lap_number"] is None
    assert e["x"] is not None and e["y"] is not None


def test_a_sample_in_the_gap_between_two_lap_rows_still_gets_a_fraction():
    """Real finding (Dutch GP, #12 lap 6->7): lap rows leave ~0.05-0.2 s gaps
    at the line; a sample inside one belongs to no timed lap. The car is still
    on the reference, so its position there keeps a fraction (LOW, no lap row
    to check continuity) instead of silently losing it."""
    from spatial_synth import at, lap_row
    rows = synth_rows(extra=(lap_row(1, 2, at(60.0), 59.9), lap_row(1, 3, at(120.2), 59.8)))
    index = _index(inputs_from_rows(SID, rows))
    before = _entry(index, 1, 119.95)                      # bracket 119.75 (L2) / 120.0 (gap)
    assert before["reference_fraction"] is not None and before["lap_number"] == 2
    assert abs(circular_diff(before["reference_fraction"], -0.05 / 60)) < 1e-8
    assert before["confidence"] == "LOW"
    after = _entry(index, 1, 120.1)                        # bracket 120.0 (gap) / 120.25 (L3)
    assert after["reference_fraction"] is not None and after["lap_number"] == 3


# --- Phase 12B: the sector of each entry -------------------------------------

def _sector_index(rows, windows_mode=None):
    import dataclasses
    inputs = inputs_from_rows(SID, rows)
    ref, finish, tol = _params(inputs)
    lines = measure_lines(inputs, ref, None)
    fractions = {n: (lines[n].fraction - finish) % 1.0 for n in ("S1", "S2")}
    windows = pit_windows(inputs, windows_mode) if windows_mode else ()
    index = _index(inputs, (ref, finish, tol), windows)
    return dataclasses.replace(index, line_fractions=fractions), fractions


def test_sector_follows_the_measured_lines():
    index, fractions = _sector_index(synth_rows())
    assert abs(fractions["S1"] - 1 / 3) < 1e-3 and abs(fractions["S2"] - 2 / 3) < 1e-3
    assert [_entry(index, 1, s)["sector"] for s in (75.0, 85.0, 105.0)] == [1, 2, 3]
    samples = trace(index, 1, _t(74.0), _t(76.0))
    assert samples and all(s["sector"] == 1 for s in samples)
    assert all(s["sector"] == 3 for s in trace(index, 1, _t(104.0), _t(106.0)))


def test_no_fraction_means_no_sector():
    index, _f = _sector_index(synth_rows(pits=(Pit(2, 3, exit_at_s=185.0),)), "EXIT")
    pit = _entry(index, 2, 175.05)
    assert pit["flag"] == "PIT_LANE" and pit["reference_fraction"] is None
    assert pit["sector"] is None
    early = next(e for e in state_at(index, _t(-10_000.0)) if e["driver_number"] == 1)
    assert early["status"] == "NO_COVERAGE" and early["sector"] is None
