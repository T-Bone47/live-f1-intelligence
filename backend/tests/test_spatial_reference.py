"""Phase 12A Task 3: the deterministic reference lap."""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise

import pytest
from spatial_synth import LENGTH, SID, SIDE, T0, Car, Pit, at, lap_row, synth_rows

from app.spatial.reference import (
    NoReferenceLap,
    build_reference,
    eligible_laps,
    reference_candidates,
)
from app.spatial.source import LapRow, inputs_from_rows


def _keys(laps: list[LapRow]) -> set[tuple[int, int]]:
    return {(r.driver, r.lap) for r in laps}


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _dist_to_square(x: float, y: float) -> float:
    edges = (abs(y) if 0 <= x <= SIDE else None, abs(x - SIDE) if 0 <= y <= SIDE else None,
             abs(y - SIDE) if 0 <= x <= SIDE else None, abs(x) if 0 <= y <= SIDE else None)
    return min(e for e in edges if e is not None)


def test_lap_1_pit_out_and_pit_adjacent_laps_are_never_eligible():
    pit_out = lap_row(3, 5, at(4.0 + 4 * 60.0), 60.0, pit_out=True)  # later row wins
    inputs = inputs_from_rows(SID, synth_rows(pits=(Pit(2, 3, exit_at_s=185.0),),
                                              extra=(pit_out,)))
    keys = _keys(eligible_laps(inputs, require_coverage=False))
    assert {(2, 3), (2, 4), (3, 5)}.isdisjoint(keys)
    assert all(lap != 1 for _d, lap in keys)
    assert (1, 2) in keys and (2, 5) in keys


def test_a_lap_with_a_location_gap_is_not_a_reference_candidate():
    rows = [r for r in synth_rows()
            if not (r[1]["type"] == "TelemetryLocationSample" and r[1]["driver_number"] == 1
                    and 80.0 < (_ts(r[1]["ts"]) - T0.timestamp()) < 83.0)]
    inputs = inputs_from_rows(SID, rows)
    assert (1, 2) not in _keys(reference_candidates(inputs, k=100))
    assert (1, 2) in _keys(eligible_laps(inputs, require_coverage=False))


def test_fastest_eligible_lap_wins_and_ties_break_by_driver_then_lap():
    tie = reference_candidates(inputs_from_rows(SID, synth_rows()))
    assert [(r.driver, r.lap) for r in tie] == [(1, 2), (1, 3), (1, 4)]
    cars = (Car(1), Car(2, 2.0, sample_phase_s=0.1), Car(3, 4.0, lap_s=59.0, sample_phase_s=0.2))
    fast = reference_candidates(inputs_from_rows(SID, synth_rows(cars=cars)))
    assert (fast[0].driver, fast[0].lap) == (3, 2)


def test_reference_is_closed_and_lies_on_the_track():
    inputs = inputs_from_rows(SID, synth_rows())
    ref = build_reference(inputs, reference_candidates(inputs)[0])
    assert (ref.driver, ref.lap) == (1, 2)
    assert ref.points[0] == ref.points[-1] and ref.centerline.is_closed
    assert all(_dist_to_square(x, y) < 1e-9 for x, y in ref.points)
    assert 0 <= LENGTH - ref.centerline.total_length <= 40
    assert all(a != b for a, b in pairwise(ref.points))  # no zero-length segment


def test_no_eligible_lap_leaves_no_candidate_and_an_empty_window_raises():
    inputs = inputs_from_rows(SID, synth_rows(laps=1))
    assert reference_candidates(inputs) == []
    empty = LapRow(driver=1, lap=9, start=T0.timestamp() + 10_000, duration=60.0,
                   s1=20.0, s2=20.0, pit_out=False)
    with pytest.raises(NoReferenceLap):
        build_reference(inputs, empty)
