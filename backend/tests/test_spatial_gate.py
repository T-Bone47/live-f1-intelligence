"""Phase 12A Task 5: cited lap lengths and the claim-scoped gate."""

from __future__ import annotations

from app.spatial.circuits import CitedLength, cited_lap_length
from app.spatial.gate import CORNER_P95_M, MAP_SECTOR_P95_M, MIN_CROSSINGS, evaluate_gate
from app.spatial.timing_lines import LineMeasurement

CITED = CitedLength(lap_length_m=4259.0, source="test citation")


def _line(name: str, p95: float, n: int = 100) -> LineMeasurement:
    disp = {"median": p95 / 2, "p90": p95, "p95": p95, "p99": p95, "max": p95}
    return LineMeasurement(line=name, fraction=0.0, x=0.0, y=0.0, n=n, exclusions={},
                           dispersion_fraction={k: v / 4259.0 for k, v in disp.items()},
                           dispersion_m=disp, worst=())


def _lines(finish: float = 10.0, s1: float = 10.0, s2: float = 10.0, n: int = 100) -> dict:
    return {"FINISH": _line("FINISH", finish, n), "S1": _line("S1", s1, n), "S2": _line("S2", s2, n)}


def test_zandvoort_is_cited_and_unknown_circuits_are_not():
    z = cited_lap_length("Zandvoort")
    assert z is not None and z.lap_length_m == 4259.0 and "http" in z.source
    assert cited_lap_length("Nowhere") is None
    assert cited_lap_length(None) is None


def test_thresholds_are_the_user_policy():
    assert (MAP_SECTOR_P95_M, CORNER_P95_M, MIN_CROSSINGS) == (20.0, 5.0, 60)


def test_map_sector_passes_at_exactly_20_m_and_fails_just_above():
    assert evaluate_gate(_lines(s2=20.0), 1.0, CITED)["MAP_SECTOR"].passed
    over = evaluate_gate(_lines(s2=20.000001), 1.0, CITED)["MAP_SECTOR"]
    assert not over.passed and over.reasons == ("P95_ABOVE_THRESHOLD:S2",)
    assert over.observed_p95_m == {"FINISH": 10.0, "S1": 10.0, "S2": 20.000001}


def test_corner_threshold_is_5_m():
    gates = evaluate_gate(_lines(5.0, 5.0, 5.0), 1.0, CITED)
    assert gates["CORNER"].passed and gates["CORNER"].threshold_m == 5.0
    gates = evaluate_gate(_lines(5.01, 5.0, 5.0), 1.0, CITED)
    assert not gates["CORNER"].passed and gates["MAP_SECTOR"].passed
    assert gates["CORNER"].reasons == ("P95_ABOVE_THRESHOLD:FINISH",)


def test_crossings_boundary_59_fails_60_passes():
    lines = _lines()
    lines["FINISH"] = _line("FINISH", 10.0, n=59)
    gates = evaluate_gate(lines, 1.0, CITED)
    assert not gates["MAP_SECTOR"].passed and not gates["CORNER"].passed
    assert "TOO_FEW_CROSSINGS:FINISH" in gates["MAP_SECTOR"].reasons
    assert evaluate_gate(_lines(n=60), 1.0, CITED)["MAP_SECTOR"].passed


def test_a_line_without_crossings_counts_as_too_few():
    lines = _lines()
    del lines["S2"]
    gate = evaluate_gate(lines, 1.0, CITED)["MAP_SECTOR"]
    assert not gate.passed and "TOO_FEW_CROSSINGS:S2" in gate.reasons
    assert gate.observed_p95_m["S2"] is None
    no_ref = evaluate_gate(None, None, CITED)["MAP_SECTOR"]
    assert not no_ref.passed and "NO_REFERENCE" in no_ref.reasons


def test_no_cited_length_fails_both_claims():
    gates = evaluate_gate(_lines(), 1.0, None)
    for claim in ("MAP_SECTOR", "CORNER"):
        assert not gates[claim].passed and "NO_CITED_LAP_LENGTH" in gates[claim].reasons


def test_unmeasured_or_reference_dependent_fails_map_sector_only():
    gates = evaluate_gate(_lines(4.0, 4.0, 4.0), None, CITED)
    assert gates["MAP_SECTOR"].reasons == ("INDEPENDENCE_UNMEASURED",)
    assert gates["CORNER"].passed
    assert evaluate_gate(_lines(), 20.5, CITED)["MAP_SECTOR"].reasons == ("REFERENCE_DEPENDENT",)
    assert evaluate_gate(_lines(), 20.0, CITED)["MAP_SECTOR"].passed
