"""Phase 12C Task 2: laps, telemetry and evidence served from a recording.

The recording is the source whenever it holds the session; the database is
used otherwise. The real case writes the unmodified Singapore pair rows into
a recording and requires the route to reproduce the committed evidence
golden byte for byte - the golden is also what the database route returns
(test_evidence_api + test_evidence_real), so both sources agree.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from spatial_synth import row, write_recording
from synthetic_lap import SID, make_lap, two_corner_profile

from app.api import HubRegistry, create_app
from app.evidence import SourceInfo, build_lap_comparison_evidence, to_canonical_json
from app.providers.openf1.mapping import to_car_sample, to_lap

ROOT = Path(__file__).parent.parent.parent
FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
GOLDEN = ROOT / "docs" / "evidence" / "evidence_v1_singapore.json"
NO_DB = "postgresql://nobody:nothing@127.0.0.1:9/none"
EVIDENCE = "/api/v1/sessions/{sid}/evidence/lap-comparison"


def session_row(sid, **over):
    model = {"session_id": sid, "provider": "openf1", "provider_session_key": sid.split(":")[-1],
             "session_type": "Race", "year": 2026, "circuit_short_name": "Synthetic",
             "meeting_name": None, **over}
    return row("SessionInfo", model, None, sid)


def model_rows(sid, lap, samples):
    rows = [row("Lap", {"type": "Lap", **lap.model_dump(mode="json")}, lap.driver_number, sid)]
    rows += [row("TelemetryCarSample", {**s.model_dump(mode="json")}, s.driver_number, sid)
             for s in samples]
    return rows


def _client(root, monkeypatch):
    monkeypatch.setenv("RECORDINGS_DIR", str(root))
    monkeypatch.setenv("DATABASE_URL", NO_DB)
    from app.config import get_settings
    get_settings.cache_clear()
    return TestClient(create_app(HubRegistry()))


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    """Two drivers, one timed lap each, a lap without duration, a null-speed sample."""
    lap_a, samples_a = make_lap(two_corner_profile(), 1)
    lap_b, samples_b = make_lap(two_corner_profile(
        speed_knots=[(0, 280), (500, 298), (600, 104), (650, 104), (900, 288), (1300, 300),
                     (1380, 148), (1420, 148), (1650, 290), (2000, 295)]), 2, phase_s=0.1)
    after = lap_a.started_at + timedelta(seconds=lap_a.duration_s + 10)
    no_duration = lap_a.model_copy(update={"lap_number": 2, "started_at": after,
                                           "duration_s": None})
    null_speed = samples_a[5].model_copy(update={"ts": after + timedelta(seconds=1),
                                                 "speed_kph": None})
    rows = [session_row(SID), *model_rows(SID, lap_a, samples_a),
            *model_rows(SID, lap_b, samples_b), *model_rows(SID, no_duration, [null_speed])]
    root = tmp_path_factory.mktemp("recordings")
    write_recording(root, rows, sid=SID, name="synthetic-10-4")
    return root, (lap_a, samples_a), (lap_b, samples_b), null_speed


@pytest.fixture
def client(synthetic, monkeypatch):
    from app.config import get_settings
    yield _client(synthetic[0], monkeypatch)
    get_settings.cache_clear()


def _q(**over):
    q = {"driver_a": 1, "lap_a": 1, "driver_b": 2, "lap_b": 1, "lap_length_m": 2000.0,
         "lap_length_source": "synthetic two-corner profile"}
    return {**q, **over}


def test_evidence_bytes_equal_direct_builder(client, synthetic):
    _root, (lap_a, samples_a), (lap_b, samples_b), _n = synthetic
    r = client.get(EVIDENCE.format(sid=SID), params=_q())
    assert r.status_code == 200, r.text
    expected = build_lap_comparison_evidence(
        lap_a, samples_a, lap_b, samples_b, lap_length_m=2000.0,
        lap_length_source="synthetic two-corner profile",
        source=SourceInfo(session_id=SID, provider="openf1", session_type="Race", season=2026,
                          event=None, circuit="Synthetic"))
    assert r.content == to_canonical_json(expected)
    assert r.headers["X-Data-Source"] == "recording"
    assert r.headers["X-Evidence-Id"] == expected.evidence_id


def test_lap_without_duration_is_422(client):
    r = client.get(EVIDENCE.format(sid=SID), params=_q(lap_a=2))
    assert r.status_code == 422 and "no duration" in r.json()["detail"]
    t = client.get(f"/api/v1/sessions/{SID}/telemetry/1", params={"lap": 2})
    assert t.status_code == 422 and "never guess" in t.json()["detail"]


def test_unknown_lap_is_404(client):
    assert client.get(EVIDENCE.format(sid=SID), params=_q(lap_b=9)).status_code == 404
    assert client.get(EVIDENCE.format(sid=SID), params=_q(driver_b=44)).status_code == 404
    assert client.get(f"/api/v1/sessions/{SID}/telemetry/1",
                      params={"lap": 9}).status_code == 404


def test_raw_telemetry_returns_every_non_null_sample(client, synthetic):
    _root, (lap_a, samples_a), _b, null_speed = synthetic
    start = lap_a.started_at.isoformat()
    end = (null_speed.ts + timedelta(seconds=1)).isoformat()
    r = client.get(f"/api/v1/sessions/{SID}/telemetry/1",
                   params={"start": start, "end": end, "frequency": "RAW",
                           "fields": "speed,throttle,gear,drs"})
    assert r.status_code == 200 and r.headers["X-Data-Source"] == "recording"
    series = r.json()["series"]
    assert len(series["speed"]) == len(samples_a)          # the null speed is omitted
    assert len(series["throttle"]) == len(samples_a) + 1   # its throttle is not
    assert [p["ts"] for p in series["speed"]] == [s.ts.isoformat() for s in samples_a]
    assert [p["value"] for p in series["gear"][:3]] == [float(s.gear) for s in samples_a[:3]]


def test_telemetry_times_need_an_offset(client, synthetic):
    r = client.get(f"/api/v1/sessions/{SID}/telemetry/1",
                   params={"start": "2026-01-01T12:00:00", "end": "2026-01-01T12:01:00"})
    assert r.status_code == 422


def test_laps_catalog_from_recording(client):
    r = client.get(f"/api/v1/sessions/{SID}/laps")
    assert r.status_code == 200 and r.headers["X-Data-Source"] == "recording"
    drivers = {d["driver_number"]: d for d in r.json()["drivers"]}
    laps = {lap["lap_number"]: lap for lap in drivers[1]["laps"]}
    assert laps[1]["has_car_telemetry"] is True and laps[1]["deleted"] is None
    assert laps[2]["duration_s"] is None and laps[2]["has_car_telemetry"] is False


def test_sessions_lists_recorded_without_db(client):
    r = client.get("/api/v1/sessions")
    body = r.json()
    assert r.status_code == 200 and body["stored_error"] == "database unavailable"
    [rec] = body["recorded"]
    assert rec["session_id"] == SID and rec["source"] == "recording"
    assert rec["timeline_available"] is True


@pytest.mark.skipif(not (FIXTURE / "meta.json").exists(), reason="no real two-driver fixture")
def test_recording_evidence_equals_the_committed_golden(tmp_path, monkeypatch):
    meta = json.loads((FIXTURE / "meta.json").read_text())
    sid = f"openf1:{meta['session_key']}"
    rows = [session_row(sid, session_type=meta["session_type"], year=meta["year"],
                        circuit_short_name=meta["circuit_short_name"])]
    for d in (meta["driver_a"], meta["driver_b"]):
        lap, _ = to_lap(json.loads((FIXTURE / f"driver_{d}_lap.json").read_text()), sid)
        car = json.loads((FIXTURE / f"driver_{d}_car_data.json").read_text())
        rows += model_rows(sid, lap, [to_car_sample(r, sid) for r in car])
    write_recording(tmp_path, rows, sid=sid, name="singapore-pair")
    c = _client(tmp_path, monkeypatch)
    r = c.get(EVIDENCE.format(sid=sid), params={
        "driver_a": meta["driver_a"], "lap_a": meta["lap_a"], "driver_b": meta["driver_b"],
        "lap_b": meta["lap_b"], "lap_length_m": meta["lap_length_m"],
        "lap_length_source": meta["lap_length_source"]})
    assert r.status_code == 200, r.text
    assert r.headers["X-Data-Source"] == "recording"
    assert r.content + b"\n" == GOLDEN.read_bytes()
