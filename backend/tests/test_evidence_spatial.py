"""Phase 12C Task 3: evidence_spatial_v1 - evidence segments placed by time.

Each driver's extent of a segment is placed from that driver's OWN first
and last sample times in the segment (evidence provenance ts_range) through
the 12A state at those times. Normalized evidence distance is never used as
a position. Synthetic geometry only (tests/spatial_synth.py).
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from spatial_synth import SID, Pit, at, location_row, row, synth_rows, write_recording

from app.analysis.timeline import to_canonical_json
from app.api import HubRegistry, create_app
from app.spatial.builder import build_spatial
from app.spatial.circuits import CitedLength
from app.spatial.contract import SpatialContractError
from app.spatial.evidence_spatial import place_evidence, validate_evidence_spatial
from app.spatial.source import inputs_from_rows
from app.spatial.state import driver_state

CIRCUITS = {"Synthetic": CitedLength(4000.0, "synthetic test geometry")}
EID = "ev1_" + "a" * 24
PIT = Pit(2, 3, exit_at_s=185.0)          # car 2 in the pit lane 165-185 s
OFF_AT = 400.13                           # one car-3 sample far off the line
GAP = (500.0, 504.0)                      # car-3 location samples removed: a 4 s gap


def _rows():
    rows = [r for r in synth_rows(laps=22, pits=(PIT,))
            if not (r[1]["type"] == "TelemetryLocationSample" and r[0]["driver_number"] == 3
                    and GAP[0] < (datetime.fromisoformat(r[1]["ts"]) - at(0)).total_seconds()
                    < GAP[1])]
    return rows + [location_row(3, at(OFF_AT), 500.0, 500.0)]


@pytest.fixture(scope="module")
def built():
    doc, index = build_spatial(inputs_from_rows(SID, _rows()), CIRCUITS)
    assert index is not None, doc["validation"]
    return doc, index


def _iso(seconds: float) -> str:
    return at(seconds).isoformat()


def _seg(i, ra, rb, status="NOT_SIGNIFICANT"):
    return {"segment_id": f"{EID}:g{i * 10}-{i * 10 + 10}", "label": f"R{i + 1:02d}",
            "attribution_status": status,
            "provenance": {"ts_range_a": None if ra is None else [_iso(ra[0]), _iso(ra[1])],
                           "ts_range_b": None if rb is None else [_iso(rb[0]), _iso(rb[1])]}}


def evidence(segments, a=1, b=2):
    return {"evidence_id": EID, "source": {"session_id": SID},
            "comparison": {"driver_a": {"driver_number": a, "lap_number": 5},
                           "driver_b": {"driver_number": b, "lap_number": 5}},
            "attribution": {"segments": segments}}


def _state(index, driver, seconds):
    return driver_state(index, driver, at(seconds).timestamp())


def test_placed_extent_equals_driver_state_at_ts_range(built):
    _doc, index = built
    ev = evidence([_seg(0, (241.0, 255.0), (243.0, 257.0)), _seg(1, (255.27, 280.0),
                                                                   (257.27, 282.0))])
    doc = place_evidence(ev, index)
    for seg, (ra, rb) in zip(doc["segments"], (((241.0, 255.0), (243.0, 257.0)),
                                               ((255.27, 280.0), (257.27, 282.0))), strict=True):
        for side, driver, (t0, t1) in (("a", 1, ra), ("b", 2, rb)):
            ext = seg[side]
            s0, s1 = _state(index, driver, t0), _state(index, driver, t1)
            assert ext["status"] == "PLACED" and ext["reason"] is None
            assert (ext["from_ts"], ext["to_ts"]) == (_iso(t0), _iso(t1))
            assert ext["from_fraction"] == s0["reference_fraction"]
            assert ext["to_fraction"] == s1["reference_fraction"]
            assert ext["from_xy"] == [s0["x"], s0["y"]] and ext["to_xy"] == [s1["x"], s1["y"]]
    validate_evidence_spatial(doc, ev)


def test_no_data_segment_not_placed_no_telemetry(built):
    _doc, index = built
    # a NO_DATA segment still carries a one-instant ts_range: it is never placed
    doc = place_evidence(evidence([_seg(0, (299.0, 299.0), (301.0, 301.0), "NO_DATA")]),
                         index)
    for side in ("a", "b"):
        ext = doc["segments"][0][side]
        assert ext["status"] == "NOT_PLACED" and ext["reason"] == "NO_TELEMETRY"
        assert ext["from_ts"] is None and ext["polyline"] is None


def test_pit_lane_extent_not_placed(built):
    _doc, index = built
    assert _state(index, 2, 175.0)["flag"] == "PIT_LANE"  # precondition
    doc = place_evidence(evidence([_seg(0, (170.0, 180.0), (170.0, 180.0))]), index)
    a, b = doc["segments"][0]["a"], doc["segments"][0]["b"]
    assert a["status"] == "PLACED"
    assert b["status"] == "NOT_PLACED" and b["reason"] == "PIT_LANE"
    assert b["from_fraction"] is None and b["from_xy"] is None and b["polyline"] is None
    assert b["from_ts"] == _iso(170.0)


def test_off_reference_extent_not_placed(built):
    _doc, index = built
    assert _state(index, 3, OFF_AT)["flag"] == "OFF_REFERENCE"  # precondition
    doc = place_evidence(evidence([_seg(0, (390.0, 395.0), (OFF_AT, 410.0))], b=3), index)
    assert doc["segments"][0]["b"]["reason"] == "OFF_REFERENCE"


def test_stale_extent_not_placed(built):
    _doc, index = built
    assert _state(index, 3, 502.0)["status"] == "STALE"  # precondition
    doc = place_evidence(evidence([_seg(0, (490.0, 495.0), (502.0, 510.0))], b=3), index)
    assert doc["segments"][0]["b"]["reason"] == "STALE"


def test_outside_coverage_not_placed(built):
    _doc, index = built
    doc = place_evidence(evidence([_seg(0, (5000.0, 5010.0), (241.0, 250.0))]), index)
    assert doc["segments"][0]["a"]["reason"] == "NO_COVERAGE"
    assert doc["segments"][0]["b"]["status"] == "PLACED"


def test_polyline_endpoints_equal_from_to_xy(built):
    _doc, index = built
    doc = place_evidence(evidence([_seg(0, (241.0, 255.0), (243.0, 257.0))]), index)
    for side in ("a", "b"):
        ext = doc["segments"][0][side]
        assert ext["polyline"][0] == ext["from_xy"] and ext["polyline"][-1] == ext["to_xy"]
        assert len(ext["polyline"]) > 2


def test_extent_across_the_line_runs_forward(built):
    _doc, index = built
    # car 1 crosses the finish line at 300 s: 295 -> 305 s is 1/6 of a lap, not 5/6
    doc = place_evidence(evidence([_seg(0, (295.0, 305.0), (296.0, 298.0))]), index)
    ext = doc["segments"][0]["a"]
    assert ext["from_fraction"] > 0.9 and ext["to_fraction"] < 0.1
    pts = ext["polyline"]
    length = sum(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
                 for (x0, y0), (x1, y1) in pairwise(pts))
    assert abs(length - 4000.0 * 10 / 60) < 0.02 * 4000.0 * 10 / 60


def test_limitations_and_precision(built):
    _doc, index = built
    doc = place_evidence(evidence([_seg(0, (241.0, 255.0), (243.0, 257.0))]), index)
    codes = {lim["code"] for lim in doc["limitations"]}
    assert {"SEGMENT_PLACED_BY_TIME", "EVIDENCE_DISTANCE_NORMALIZED_NOT_POSITION",
            "EXTENT_IS_SAMPLE_BOUNDED", "INTERPOLATED_BETWEEN_SAMPLES"} <= codes
    assert ("CORNER_PRECISION_NOT_MET" in codes) is (not index.corner_precision_met)
    assert doc["line_placement_p95_m"] == index.line_p95_m
    unmet = copy.copy(index)
    unmet.corner_precision_met = False
    codes = {lim["code"] for lim in place_evidence(
        evidence([_seg(0, (241.0, 255.0), (243.0, 257.0))]), unmet)["limitations"]}
    assert "CORNER_PRECISION_NOT_MET" in codes


@pytest.mark.parametrize("tamper", [
    "other evidence id", "segments reordered", "placed without a fraction",
    "not placed with a polyline", "fraction of a whole lap", "extra field",
    "driver swapped", "no-data segment placed", "polyline off its endpoints"])
def test_tampered_documents_are_refused(built, tamper):
    _doc, index = built
    ev = evidence([_seg(0, (241.0, 255.0), (243.0, 257.0)), _seg(1, (170.0, 180.0),
                                                                   (170.0, 180.0)),
                   _seg(2, (299.0, 299.0), (301.0, 301.0), "NO_DATA")])
    doc = json.loads(json.dumps(place_evidence(ev, index)))
    validate_evidence_spatial(doc, ev)  # the untampered document passes
    placed, pit, nodata = doc["segments"]
    if tamper == "other evidence id":
        doc["evidence_id"] = "ev1_" + "b" * 24
    elif tamper == "segments reordered":
        doc["segments"] = [pit, placed, nodata]
    elif tamper == "placed without a fraction":
        placed["a"]["from_fraction"] = None
    elif tamper == "not placed with a polyline":
        pit["b"]["polyline"] = placed["a"]["polyline"]
    elif tamper == "fraction of a whole lap":
        placed["a"]["to_fraction"] = 1.0
    elif tamper == "extra field":
        placed["a"]["corner"] = "Tarzan"
    elif tamper == "driver swapped":
        doc["driver_b"] = 3
    elif tamper == "no-data segment placed":
        nodata["a"] = placed["a"]
    elif tamper == "polyline off its endpoints":
        placed["a"]["polyline"][0] = [0.0, 0.0]
    with pytest.raises(SpatialContractError):
        validate_evidence_spatial(doc, ev)


# ---------------------------------------------------------------- route

CAR = {"rpm": 11000, "speed_kph": 240, "gear": 8, "throttle_pct": 100.0, "brake_pct": 0.0,
       "drs": None, "provenance": {"provider": "openf1", "provenance_class": "B"}}


def _car_rows(driver: int, start_s: float):
    """Constant 240 kph (4000 m in 60 s, the synthetic lap) at ~3.7 Hz."""
    n = int(60.0 / 0.27) + 1
    return [row("TelemetryCarSample", {"session_id": SID, "driver_number": driver,
                                       "ts": at(start_s + k * 0.27).isoformat(), **CAR}, driver)
            for k in range(n)]


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    rows = synth_rows(laps=22, pits=(PIT,), extra=tuple(_car_rows(1, 240.0) + _car_rows(2, 242.0)))
    return write_recording(tmp_path_factory.mktemp("rec"), rows)


@pytest.fixture
def api(tmp_path, monkeypatch, pristine):
    root = tmp_path / "recordings"
    dest = root / pristine.name
    dest.mkdir(parents=True)
    for name in ("frames.jsonl.zst", "meta.json"):
        shutil.copy2(pristine / name, dest / name)
    circuits = tmp_path / "circuits.json"
    circuits.write_text(json.dumps({"Synthetic": {"lap_length_m": 4000.0,
                                                  "source": "synthetic test geometry"}}))
    monkeypatch.setattr("app.spatial.circuits.CIRCUITS_PATH", circuits)
    monkeypatch.setenv("RECORDINGS_DIR", str(root))
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:9/none")
    from app.config import get_settings
    get_settings.cache_clear()
    yield TestClient(create_app(HubRegistry())), circuits
    get_settings.cache_clear()


Q = {"driver_a": 1, "lap_a": 5, "driver_b": 2, "lap_b": 5, "lap_length_m": 4000.0,
     "lap_length_source": "synthetic test geometry"}


def test_route_places_the_routes_own_evidence(api):
    c, _circuits = api
    ev = c.get(f"/api/v1/sessions/{SID}/evidence/lap-comparison", params=Q)
    assert ev.status_code == 200, ev.text
    r = c.get(f"/api/v1/sessions/{SID}/evidence/lap-comparison/spatial", params=Q)
    assert r.status_code == 200, r.text
    assert r.headers["X-Spatial-Contract"] == "evidence_spatial_v1"
    assert r.headers["X-Evidence-Id"] == ev.headers["X-Evidence-Id"]
    assert r.headers["X-Data-Source"] == "recording"
    body = json.loads(r.content)
    validate_evidence_spatial(body, json.loads(ev.content))
    assert r.content == to_canonical_json(body)
    placed = [s["a"]["status"] for s in body["segments"]]
    assert "PLACED" in placed


def test_unvalidated_track_409_with_reasons(api):
    c, circuits = api
    circuits.write_text("{}")  # no citation: the gate cannot pass
    r = c.get(f"/api/v1/sessions/{SID}/evidence/lap-comparison/spatial", params=Q)
    assert r.status_code == 409 and r.json()["detail"]["reasons"]


def test_no_recording_404(api):
    c, _circuits = api
    r = c.get("/api/v1/sessions/openf1:404/evidence/lap-comparison/spatial", params=Q)
    assert r.status_code == 404


def test_bad_request_422(api):
    c, _circuits = api
    r = c.get(f"/api/v1/sessions/{SID}/evidence/lap-comparison/spatial",
              params={**Q, "lap_length_m": 0})
    assert r.status_code == 422


def test_times_are_utc(built):
    _doc, index = built
    doc = place_evidence(evidence([_seg(0, (241.0, 255.0), (243.0, 257.0))]), index)
    assert datetime.fromisoformat(doc["segments"][0]["a"]["from_ts"]).tzinfo == UTC
