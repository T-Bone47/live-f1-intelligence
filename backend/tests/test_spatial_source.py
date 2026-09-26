"""Phase 12A Task 2: session spatial inputs from a recording, identity-guarded."""

from __future__ import annotations

import random
from itertools import pairwise

import pytest
from spatial_synth import (
    DEFAULT_CARS,
    SID,
    T0,
    at,
    car_sample_row,
    expected_xy,
    lap_row,
    location_row,
    synth_rows,
    write_recording,
)

from app.spatial.source import SpatialIdentityError, inputs_from_rows, load_inputs


def test_rows_are_bucketed_by_their_own_driver_and_time_sorted():
    rows = synth_rows()
    random.Random(7).shuffle(rows)
    inputs = inputs_from_rows(SID, rows)
    assert inputs.drivers == (1, 2, 3)
    for car in DEFAULT_CARS:
        samples = inputs.samples[car.number]
        assert all(a[0] < b[0] for a, b in pairwise(samples))
        for t, x, y in samples:
            ex, ey = expected_xy(car, round(t - T0.timestamp(), 6))  # ISO timestamps carry µs
            assert abs(x - ex) < 1e-6 and abs(y - ey) < 1e-6
    assert [lap.lap for lap in inputs.laps[2]] == [1, 2, 3, 4, 5, 6]


def test_a_row_from_another_session_fails_closed():
    rows = synth_rows(extra=(lap_row(1, 9, at(999.0), 60.0, sid="openf1:2"),))
    with pytest.raises(SpatialIdentityError, match="openf1:2"):
        inputs_from_rows(SID, rows)


def test_an_envelope_driver_that_disagrees_with_its_model_fails_closed():
    meta, model = location_row(1, at(10.0), 5.0, 5.0)
    rows = synth_rows(extra=(({**meta, "driver_number": 2}, model),))
    with pytest.raises(SpatialIdentityError, match="driver"):
        inputs_from_rows(SID, rows)


def test_null_and_zero_triple_positions_are_dropped_and_counted():
    extra = (location_row(1, at(1000.01), None, 7.0), location_row(1, at(1000.02), 0.0, 0.0, 0.0))
    inputs = inputs_from_rows(SID, synth_rows(extra=extra))
    assert inputs.counts["null_xy"] == 1 and inputs.counts["no_fix"] == 1
    kept = {round(t - T0.timestamp(), 3) for t, _x, _y in inputs.samples[1]}
    assert 1000.01 not in kept and 1000.02 not in kept


def test_identical_duplicates_keep_one_and_conflicting_duplicates_drop_all():
    extra = (location_row(1, at(10.0), *expected_xy(DEFAULT_CARS[0], 10.0)),
             location_row(1, at(20.0), 1.0, 2.0))
    inputs = inputs_from_rows(SID, synth_rows(extra=extra))
    assert inputs.counts["duplicate_identical"] == 1
    assert inputs.counts["duplicate_conflicting"] == 2
    times = [round(t - T0.timestamp(), 6) for t, _x, _y in inputs.samples[1]]
    assert times.count(10.0) == 1 and 20.0 not in times


def test_load_inputs_reads_a_recording_and_counts_drs_nulls(tmp_path):
    extra = (car_sample_row(1, at(5.0), None), car_sample_row(1, at(5.3), None),
             car_sample_row(2, at(5.0), 8))
    rows = synth_rows(extra=extra)
    rec = write_recording(tmp_path, rows)
    inputs = load_inputs(rec, SID)
    assert inputs.counts["car_samples"] == 3 and inputs.counts["car_drs_null"] == 2
    assert inputs.input_digest == inputs_from_rows(SID, rows).input_digest
    assert inputs.session["circuit_short_name"] == "Synthetic"


def test_input_digest_changes_when_any_sample_changes():
    base = inputs_from_rows(SID, synth_rows()).input_digest
    moved = inputs_from_rows(SID, synth_rows(extra=(location_row(3, at(33.33), 1.0, 1.0),)))
    assert moved.input_digest != base
