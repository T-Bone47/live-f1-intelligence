"""Phase 12A Task 4: the official timing lines, measured on the reference."""

from __future__ import annotations

from datetime import datetime

import pytest
from spatial_synth import (
    DEFAULT_CARS,
    FINISH_S,
    SID,
    T0,
    Pit,
    at,
    crossing,
    lap_row,
    synth_rows,
    track_xy,
)

from app.spatial.reference import build_reference, reference_candidates
from app.spatial.source import inputs_from_rows
from app.spatial.timing_lines import (
    circular_diff,
    circular_median,
    inter_line_fractions,
    measure_lines,
    nearest_rank,
    position_at,
    reference_independence_m,
)

# Epoch-second doubles resolve ~2.4e-7 s; at 66.7 units/s that is ~1.6e-5
# units, so "exact" synthetic geometry is checked to 1e-4 (ledger ruling).
EXACT = 1e-4


def _setup(**kw):
    inputs = inputs_from_rows(SID, synth_rows(**kw))
    return inputs, build_reference(inputs, reference_candidates(inputs)[0])


def test_nearest_rank_and_circular_median():
    assert nearest_rank(range(1, 11), 0.95) == 10
    assert nearest_rank(range(1, 11), 0.9) == 9
    with pytest.raises(ValueError):
        nearest_rank([], 0.5)
    assert abs(circular_diff(circular_median([0.98, 0.99, 0.01, 0.02]), 0.0)) < 1e-12
    assert circular_median([0.2, 0.4, 0.3]) == 0.3


def test_position_at_interpolates_within_a_bracket_and_refuses_gaps():
    samples = [(0.0, 0.0, 0.0), (1.0, 10.0, 0.0), (4.0, 40.0, 0.0)]
    assert position_at(samples, 0.5) == (5.0, 0.0)
    assert position_at(samples, 1.0) == (10.0, 0.0)
    assert position_at(samples, 2.5) is None      # bracket gap 3 s > MAX_GAP_S
    assert position_at(samples, -1.0) is None     # outside the samples


def test_lines_on_exact_geometry_have_zero_dispersion_and_known_spacing():
    inputs, ref = _setup()
    lines = measure_lines(inputs, ref, lap_length_m=4000.0)
    assert set(lines) == {"FINISH", "S1", "S2"}
    for m in lines.values():
        assert m.dispersion_m["max"] < EXACT and m.n > 0
    f_s1, s1_s2, s2_f = inter_line_fractions(lines)
    assert abs(f_s1 - 1 / 3) < 1e-8 and abs(s1_s2 - 1 / 3) < 1e-8 and abs(s2_f - 1 / 3) < 1e-8
    fx, fy = track_xy(FINISH_S)
    assert abs(lines["FINISH"].x - fx) < EXACT and abs(lines["FINISH"].y - fy) < EXACT


def test_exclusions_are_counted_by_reason():
    no_s1 = lap_row(3, 5, at(crossing(DEFAULT_CARS[2], 4)), 60.0)
    no_s1[1]["sector1_s"] = None
    extra = (no_s1,
             lap_row(1, 7, at(1000.0), 60.0),     # beyond every sample: NO_BRACKET
             lap_row(2, 7, at(430.0), None))      # untimed
    rows = [r for r in synth_rows(pits=(Pit(2, 3, exit_at_s=185.0),), extra=extra)
            if not (r[1]["type"] == "TelemetryLocationSample" and r[1]["driver_number"] == 1
                    and 179.0 < datetime.fromisoformat(r[1]["ts"]).timestamp()
                    - T0.timestamp() < 181.5)]     # a gap around car 1's lap-4 start
    inputs = inputs_from_rows(SID, rows)
    lines = measure_lines(inputs, build_reference(inputs, reference_candidates(inputs)[0]), 4000.0)
    fin, s1, s2 = lines["FINISH"].exclusions, lines["S1"].exclusions, lines["S2"].exclusions
    assert (fin["LAP_1"], fin["PIT_ADJACENT"], fin["UNTIMED"]) == (3, 2, 1)
    assert (fin["GAP"], fin["NO_BRACKET"], fin["NO_SECTOR_TIME"]) == (1, 1, 0)
    assert (s1["NO_SECTOR_TIME"], s2["NO_SECTOR_TIME"], s1["GAP"]) == (1, 1, 0)
    assert s1["NO_BRACKET"] == 1 and s2["NO_BRACKET"] == 1


def test_a_displaced_crossing_is_kept_and_listed_as_worst():
    base = measure_lines(*_setup(), lap_length_m=4000.0)
    shifted = lap_row(2, 4, at(crossing(DEFAULT_CARS[1], 3) + 0.6), 60.0)  # later row wins
    lines = measure_lines(*_setup(extra=(shifted,)), lap_length_m=4000.0)
    for name, m in lines.items():
        assert m.n == base[name].n                       # kept, not trimmed
        assert m.worst[0][:2] == (2, 4)
        assert abs(m.worst[0][2] - 40.0) < EXACT         # 0.6 s at 66.7 units/s


def test_dispersion_metres_need_a_cited_length():
    lines = measure_lines(*_setup(), lap_length_m=None)
    for m in lines.values():
        assert m.dispersion_m is None
        assert set(m.dispersion_fraction) == {"median", "p90", "p95", "p99", "max"}


def test_reference_independence_is_zero_on_exact_geometry():
    inputs = inputs_from_rows(SID, synth_rows())
    refs = [build_reference(inputs, lap) for lap in reference_candidates(inputs)]
    assert len(refs) == 3
    assert reference_independence_m(inputs, refs, 4000.0) < EXACT
    assert reference_independence_m(inputs, refs, None) is None
    assert reference_independence_m(inputs, refs[:1], 4000.0) is None
