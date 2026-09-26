"""Phase 12A Task 10: the spatial routes (track, state at t, driver trace)."""

from __future__ import annotations

import json
import shutil
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from spatial_synth import SID, T0, synth_rows, write_recording

from app.analysis.timeline import to_canonical_json
from app.api import HubRegistry, create_app
from app.spatial.builder import build_spatial
from app.spatial.source import load_inputs


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    return write_recording(tmp_path_factory.mktemp("rec"), synth_rows(laps=22))


@pytest.fixture
def cited(tmp_path, monkeypatch):
    path = tmp_path / "circuits.json"
    path.write_text(json.dumps({"Synthetic": {"lap_length_m": 4000.0,
                                              "source": "synthetic test geometry"}}))
    monkeypatch.setattr("app.spatial.circuits.CIRCUITS_PATH", path)


@pytest.fixture
def client(tmp_path, monkeypatch, pristine):
    root = tmp_path / "recordings"
    dest = root / pristine.name
    dest.mkdir(parents=True)
    for name in ("frames.jsonl.zst", "meta.json"):
        shutil.copy2(pristine / name, dest / name)
    monkeypatch.setenv("RECORDINGS_DIR", str(root))
    from app.config import get_settings
    get_settings.cache_clear()
    yield TestClient(create_app(HubRegistry())), dest
    get_settings.cache_clear()


def _iso(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def test_track_route_serves_the_builder_bytes(client, cited):
    c, rec = client
    r = c.get(f"/api/v1/sessions/{SID}/track")
    assert r.status_code == 200 and r.headers["X-Spatial-Contract"] == "track_reference_v1"
    assert r.content == to_canonical_json(build_spatial(load_inputs(rec, SID))[0])


def test_state_route_positions_every_car_mid_race(client, cited):
    c, _rec = client
    r = c.get(f"/api/v1/sessions/{SID}/spatial", params={"at": _iso(300.05)})
    assert r.status_code == 200 and r.headers["X-Spatial-Contract"] == "spatial_state_v1"
    drivers = r.json()["drivers"]
    assert [d["driver_number"] for d in drivers] == [1, 2, 3]
    assert all(d["status"] == "POSITIONED" and d["flag"] == "ON_REFERENCE" for d in drivers)


def test_at_with_an_offset_is_converted_to_utc_and_naive_at_is_422(client, cited):
    c, _rec = client
    utc = c.get(f"/api/v1/sessions/{SID}/spatial", params={"at": "2026-01-01T12:05:00.050000Z"})
    plus2 = c.get(f"/api/v1/sessions/{SID}/spatial",
                  params={"at": "2026-01-01T14:05:00.050000+02:00"})
    assert utc.status_code == plus2.status_code == 200 and utc.content == plus2.content
    naive = c.get(f"/api/v1/sessions/{SID}/spatial", params={"at": "2026-01-01T12:05:00"})
    assert naive.status_code == 422 and "UTC offset" in naive.json()["detail"]
    garbage = c.get(f"/api/v1/sessions/{SID}/spatial", params={"at": "lap 12"})
    assert garbage.status_code == 422


def test_trace_route_limits_and_errors(client, cited):
    c, _rec = client
    url = f"/api/v1/sessions/{SID}/spatial"
    ok = c.get(f"{url}/2", params={"from": _iso(100.0), "to": _iso(160.0)})
    assert ok.status_code == 200 and ok.headers["X-Spatial-Contract"] == "spatial_trace_v1"
    assert len(ok.json()["samples"]) == 240
    assert c.get(f"{url}/2", params={"from": _iso(160.0), "to": _iso(100.0)}).status_code == 422
    assert c.get(f"{url}/2", params={"from": _iso(0.0), "to": _iso(601.0)}).status_code == 422
    assert c.get(f"{url}/0", params={"from": _iso(0.0), "to": _iso(60.0)}).status_code == 422
    assert c.get(f"{url}/42", params={"from": _iso(0.0), "to": _iso(60.0)}).status_code == 404


def test_unvalidated_geometry_is_409_with_reasons(client):
    c, _rec = client                       # no citation for "Synthetic"
    r = c.get(f"/api/v1/sessions/{SID}/spatial", params={"at": _iso(300.05)})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["status"] == "UNVALIDATED" and "NO_CITED_LAP_LENGTH" in detail["reasons"]
    track = c.get(f"/api/v1/sessions/{SID}/track")
    assert track.status_code == 200 and track.json()["status"] == "UNVALIDATED"


def test_session_without_reference_lap_is_409(tmp_path, monkeypatch, cited):
    write_recording(tmp_path / "recordings", synth_rows(laps=1))
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path / "recordings"))
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        c = TestClient(create_app(HubRegistry()))
        r = c.get(f"/api/v1/sessions/{SID}/spatial", params={"at": _iso(10.0)})
        assert r.status_code == 409
        assert r.json()["detail"]["reasons"] == ["NO_ELIGIBLE_REFERENCE_LAP"]
    finally:
        get_settings.cache_clear()


def test_no_recording_is_404_for_all_three_routes(client, cited):
    c, _rec = client
    other = "openf1:777"
    for r in (c.get(f"/api/v1/sessions/{other}/track"),
              c.get(f"/api/v1/sessions/{other}/spatial", params={"at": _iso(1.0)}),
              c.get(f"/api/v1/sessions/{other}/spatial/1",
                    params={"from": _iso(0.0), "to": _iso(1.0)})):
        assert r.status_code == 404 and "no recording" in r.json()["detail"]


def test_repeated_requests_are_byte_identical(client, cited):
    c, _rec = client
    a = c.get(f"/api/v1/sessions/{SID}/spatial", params={"at": _iso(412.3)})
    b = c.get(f"/api/v1/sessions/{SID}/spatial", params={"at": _iso(412.3)})
    assert a.status_code == 200 and a.content == b.content


def test_legacy_circuit_route_is_unchanged(client):
    c, _rec = client
    assert c.get(f"/api/v1/sessions/{SID}/circuit").status_code == 404   # no hub: as before
