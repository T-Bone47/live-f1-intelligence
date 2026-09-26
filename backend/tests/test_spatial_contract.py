"""Phase 12A Task 8: versioned, fail-closed spatial contracts and the builder."""

from __future__ import annotations

import copy
import json
import math
import random
from datetime import UTC, datetime, timedelta

import pytest
from spatial_synth import SID, T0, car_sample_row, synth_rows

from app.analysis.timeline import to_canonical_json
from app.spatial.builder import build_spatial, state_doc, trace_doc
from app.spatial.circuits import CitedLength
from app.spatial.contract import (
    SpatialContractError,
    make_track_id,
    validate_state,
    validate_trace,
    validate_track,
)
from app.spatial.source import inputs_from_rows

CIRCUITS = {"Synthetic": CitedLength(4000.0, "synthetic test geometry")}
VALID_LAPS = 22   # 3 cars x 21 eligible laps = 63 crossings per line (gate needs 60)


@pytest.fixture(scope="module")
def valid():
    extra = (car_sample_row(1, T0, None), car_sample_row(2, T0, None))
    inputs = inputs_from_rows(SID, synth_rows(laps=VALID_LAPS, extra=extra),
                              counts={"car_samples": 2, "car_drs_null": 2})
    doc, index = build_spatial(inputs, CIRCUITS)
    return inputs, doc, index


def test_synthetic_track_doc_validates_and_is_deterministic(valid):
    inputs, doc, index = valid
    assert doc["status"] == "VALIDATED_MAP_SECTOR" and index is not None
    validate_track(doc)
    assert to_canonical_json(build_spatial(inputs, CIRCUITS)[0]) == to_canonical_json(doc)
    assert doc["reference"]["polyline"][0] == doc["reference"]["polyline"][-1]
    finish = next(line for line in doc["timing_lines"] if line["line"] == "FINISH")
    assert finish["distance_m"] == 0.0


def test_state_and_trace_docs_validate_at_any_time(valid):
    _inputs, _doc, index = valid
    rng = random.Random(5)
    for _ in range(60):
        at = T0 + timedelta(seconds=rng.uniform(-20.0, 1400.0))
        validate_state(state_doc(index, at))
    validate_trace(trace_doc(index, 2, T0 + timedelta(seconds=100), T0 + timedelta(seconds=160)))


def test_track_id_changes_with_data_version_and_citation():
    base = make_track_id(SID, "abc", CIRCUITS["Synthetic"])
    assert base.startswith("trk1_") and len(base) == 5 + 24
    assert make_track_id(SID, "abd", CIRCUITS["Synthetic"]) != base
    assert make_track_id(SID, "abc", None) != base
    assert make_track_id(SID, "abc", CitedLength(4000.0, "other source")) != base
    assert make_track_id("openf1:2", "abc", CIRCUITS["Synthetic"]) != base


def test_unvalidated_session_has_no_polyline_and_no_index():
    doc, index = build_spatial(inputs_from_rows(SID, synth_rows(laps=VALID_LAPS)), {})
    validate_track(doc)
    assert doc["status"] == "UNVALIDATED" and index is None
    assert doc["reference"]["polyline"] is None
    assert "NO_CITED_LAP_LENGTH" in doc["validation"]["reasons"]
    assert doc["circuit"]["lap_length_m"] is None
    assert all(line["distance_m"] is None and line["dispersion_m"] is None
               for line in doc["timing_lines"])
    # spec 5.4: no geometry on unvalidated geometry - line positions withheld too,
    # while the measured dispersion stays as evidence
    assert doc["timing_lines"] and all(
        (line["x"], line["y"], line["loop_fraction"]) == (None, None, None)
        and line["n"] > 0 for line in doc["timing_lines"])


def test_validated_track_publishes_three_contiguous_sectors(valid):
    """Phase 12B: the browser never computes sectors - the track document
    carries their paths, from line to line, measured on the reference."""
    _inputs, doc, _index = valid
    lines = {line["line"]: line for line in doc["timing_lines"]}
    sectors = doc["sectors"]
    assert [s["sector"] for s in sectors] == [1, 2, 3]
    assert [(s["from_line"], s["to_line"]) for s in sectors] == [
        ("FINISH", "S1"), ("S1", "S2"), ("S2", "FINISH")]
    for s in sectors:
        start, end = lines[s["from_line"]], lines[s["to_line"]]
        assert s["polyline"][0] == [start["x"], start["y"]]
        assert s["polyline"][-1] == [end["x"], end["y"]]
        assert len(s["label_point"]) == 2
    assert abs(sum(s["length_m"] for s in sectors) - 4000.0) < 1e-6
    for s in sectors:
        span = (lines[s["to_line"]]["loop_fraction"] - lines[s["from_line"]]["loop_fraction"]) % 1.0
        assert s["length_m"] == span * 4000.0


def test_unvalidated_track_has_no_sectors():
    doc, _index = build_spatial(inputs_from_rows(SID, synth_rows(laps=VALID_LAPS)), {})
    assert doc["status"] == "UNVALIDATED" and doc["sectors"] == []


def test_no_eligible_reference_lap_is_unvalidated():
    doc, index = build_spatial(inputs_from_rows(SID, synth_rows(laps=1)), CIRCUITS)
    validate_track(doc)
    assert index is None and doc["status"] == "UNVALIDATED"
    assert doc["reference"] is None and doc["timing_lines"] == []
    assert doc["validation"]["reasons"] == ["NO_ELIGIBLE_REFERENCE_LAP"]


def test_capabilities_state_no_corners_no_drs_no_racing_line_with_evidence(valid):
    _inputs, doc, _index = valid
    caps = doc["capabilities"]
    assert all(c["available"] is False for c in caps.values())
    assert caps["drs_zones"]["evidence"] == {"car_samples": 2, "drs_null": 2}
    assert set(caps["racing_line"]["evidence"]) == {"p50", "p90", "p99", "p999"}
    codes = {lim["code"] for lim in doc["limitations"]}
    assert {"FEED_LINE_NOT_RACING_LINE", "CORNERS_UNAVAILABLE", "DRS_DATA_ABSENT",
            "RECORDING_ONLY", "METRES_NORMALIZED_TO_CITED_LENGTH"} <= codes


def _mid_state(index) -> dict:
    return state_doc(index, T0 + timedelta(seconds=300.05))


def _t_extra(d, _s): d["cause"] = "braking"
def _t_nan(d, _s): d["timing_lines"][0]["dispersion_m"]["p95"] = math.nan
def _t_unvalidated_polyline(d, _s): d["status"] = "UNVALIDATED"
def _t_track_id(d, _s): d["track_id"] = "trk1_" + "0" * 24
def _t_unvalidated_line_position(d, _s):
    d["status"] = "UNVALIDATED"
    d["reference"]["polyline"] = None       # only the line positions still leak
def _t_status(d, _s): d["status"] = "VALIDATED_EVERYTHING"
def _t_unvalidated_sectors(d, _s):
    d["status"] = "UNVALIDATED"
    d["reference"]["polyline"] = None
    for line in d["timing_lines"]:          # only the sector paths still leak
        line.update(loop_fraction=None, x=None, y=None, distance_m=None)
def _t_sector_lengths(d, _s): d["sectors"][1]["length_m"] += 1.0
def _t_sector_endpoint(d, _s): d["sectors"][2]["polyline"][0][0] += 0.5
def _t_sector_order(d, _s): d["sectors"][0], d["sectors"][1] = d["sectors"][1], d["sectors"][0]
def _s_fraction_pit(_d, s): s["drivers"][0]["flag"] = "PIT_LANE"
def _s_metres_uncited(_d, s): s["lap_length_m"] = None
def _s_no_bracket(_d, s): s["drivers"][0]["bracket"] = None
def _s_stale_no_age(_d, s): s["drivers"][0]["status"] = "STALE"
def _s_duplicate(_d, s): s["drivers"].append(copy.deepcopy(s["drivers"][0]))


@pytest.mark.parametrize("tamper", [_t_extra, _t_nan, _t_unvalidated_polyline,
                                    _t_unvalidated_line_position, _t_track_id,
                                    _t_status, _t_unvalidated_sectors, _t_sector_lengths,
                                    _t_sector_endpoint, _t_sector_order, _s_fraction_pit, _s_metres_uncited, _s_no_bracket,
                                    _s_stale_no_age, _s_duplicate])
def test_tampered_documents_are_rejected(valid, tamper):
    _inputs, doc, index = valid
    track, state = copy.deepcopy(doc), json.loads(json.dumps(_mid_state(index)))
    assert state["drivers"][0]["reference_fraction"] is not None   # tamper targets are live
    tamper(track, state)
    with pytest.raises(SpatialContractError):
        validate_track(track)
        validate_state(state)


def test_state_doc_at_carries_utc(valid):
    _inputs, _doc, index = valid
    at = datetime(2026, 1, 1, 14, 0, 15, tzinfo=UTC).astimezone()
    assert state_doc(index, at)["at"] == "2026-01-01T14:00:15+00:00"


def test_state_and_trace_docs_state_their_precision(valid):
    """Final review I3: a consumer holding only a state or trace document must
    see how precisely positions are placed and whether corner-level metre
    claims are refused."""
    import dataclasses
    _inputs, doc, index = valid
    expected = {line["line"]: line["dispersion_m"]["p95"] for line in doc["timing_lines"]}
    state = state_doc(index, T0 + timedelta(seconds=300.0))
    trace = trace_doc(index, 1, T0 + timedelta(seconds=100), T0 + timedelta(seconds=120))
    assert state["line_placement_p95_m"] == expected == trace["line_placement_p95_m"]
    corner_ok = doc["validation"]["gates"]["CORNER"]["passed"]
    codes = {lim["code"] for lim in state["limitations"]}
    assert ("CORNER_PRECISION_NOT_MET" in codes) is (not corner_ok)
    refused = dataclasses.replace(index, corner_precision_met=False)
    for d in (state_doc(refused, T0 + timedelta(seconds=300.0)),
              trace_doc(refused, 1, T0 + timedelta(seconds=100), T0 + timedelta(seconds=120))):
        assert "CORNER_PRECISION_NOT_MET" in {lim["code"] for lim in d["limitations"]}
