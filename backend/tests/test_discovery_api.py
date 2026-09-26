"""Phase 11 session / driver / lap discovery - REAL rows through REAL Postgres.

GET /api/v1/sessions             active hubs (unchanged) + stored sessions
GET /api/v1/sessions/{sid}/laps  stored drivers and laps of one session

Seeded with the real Singapore pair (OpenF1 9161, unmodified rows). Nothing is
looked up elsewhere: absent metadata stays null. Skips without Postgres.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import HubRegistry, create_app
from app.core.enums import ProvenanceClass, ProviderName, SessionType
from app.core.models import Lap, Provenance, SessionInfo
from app.providers.openf1.mapping import to_car_sample, to_lap
from app.storage.db import Repository

ROOT = Path(__file__).parent.parent.parent
FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
DB = os.environ.get("TEST_DATABASE_URL",
                    "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel")

pytestmark = pytest.mark.skipif(not (FIXTURE / "meta.json").exists(),
                                reason="no real two-driver fixture")


@pytest.fixture
async def seeded(pg_pool):
    meta = json.loads((FIXTURE / "meta.json").read_text())
    tag = uuid.uuid4().hex[:12]
    sid = f"pytest:disc:{tag}"
    repo = Repository(pg_pool)
    await repo.upsert_session(SessionInfo(
        session_id=sid, provider=ProviderName.OPENF1, provider_session_key=f"disc-{tag}",
        session_type=SessionType.QUALIFYING, year=meta["year"],
        circuit_short_name=meta["circuit_short_name"],
        provenance=Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.B)))
    laps = {}
    for d in (meta["driver_a"], meta["driver_b"]):
        laps[d], _ = to_lap(json.loads((FIXTURE / f"driver_{d}_lap.json").read_text()), sid)
        await repo.insert_lap(laps[d])
        rows = json.loads((FIXTURE / f"driver_{d}_car_data.json").read_text())
        samples = sorted((to_car_sample(r, sid) for r in rows), key=lambda s: s.ts)
        await repo.insert_car_samples_bulk([
            (s.session_id, s.driver_number, s.ts, s.rpm, s.speed_kph, s.gear, s.throttle_pct,
             s.brake_pct, s.drs, s.provenance.provenance_class.value) for s in samples])
    yield sid, meta, laps
    for table in ("telemetry_car", "laps", "sessions"):
        await pg_pool.execute(f"DELETE FROM {table} WHERE session_id=$1", sid)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", DB)
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path))     # no recordings
    from app.config import get_settings
    get_settings.cache_clear()
    yield TestClient(create_app(HubRegistry()))
    get_settings.cache_clear()


async def test_stored_sessions_list_real_metadata_only(seeded, client):
    sid, meta, _laps = seeded
    body = client.get("/api/v1/sessions").json()
    assert body["active"] == []
    row = next(s for s in body["stored"] if s["session_id"] == sid)
    assert row["provider"] == "openf1"
    assert row["year"] == meta["year"]
    assert row["session_type"] == "Qualifying"
    assert row["circuit_short_name"] == meta["circuit_short_name"]
    assert row["meeting_name"] is None               # not recorded -> null, never guessed
    assert row["drivers"] == 2 and row["laps"] == 2
    assert row["max_lap"] == max(meta["lap_a"], meta["lap_b"])
    assert row["has_car_telemetry"] is True
    assert row["timeline_available"] is False        # no recording, no hub


async def test_session_laps_lists_each_drivers_real_laps(seeded, client):
    sid, meta, laps = seeded
    body = client.get(f"/api/v1/sessions/{sid}/laps").json()
    assert body["session_id"] == sid
    by_num = {d["driver_number"]: d for d in body["drivers"]}
    assert set(by_num) == {meta["driver_a"], meta["driver_b"]}
    a = by_num[meta["driver_a"]]
    # identity was never stored for this session: null, not invented
    assert a["acronym"] is None and a["team_name"] is None
    (lap,) = a["laps"]
    assert lap["lap_number"] == meta["lap_a"]
    assert lap["duration_s"] == laps[meta["driver_a"]].duration_s
    assert lap["has_car_telemetry"] is True
    assert lap["deleted"] is False


async def test_a_lap_without_stored_telemetry_is_marked(seeded, client, pg_pool):
    sid, meta, laps = seeded
    ref = laps[meta["driver_a"]]
    extra = Lap(session_id=sid, driver_number=meta["driver_a"], lap_number=ref.lap_number + 5,
                started_at=ref.started_at + timedelta(minutes=20), duration_s=None,
                provenance=ref.provenance)            # test row: no time, no telemetry
    await Repository(pg_pool).insert_lap(extra)
    body = client.get(f"/api/v1/sessions/{sid}/laps").json()
    a = next(d for d in body["drivers"] if d["driver_number"] == meta["driver_a"])
    added = next(lap for lap in a["laps"] if lap["lap_number"] == ref.lap_number + 5)
    assert added["duration_s"] is None and added["has_car_telemetry"] is False


async def test_unknown_or_invalid_session_fails_explicitly(seeded, client):
    assert client.get("/api/v1/sessions/pytest:disc:none/laps").status_code == 404
    assert client.get("/api/v1/sessions/bad id/laps").status_code == 422


def test_sessions_list_survives_an_unreachable_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/none")
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        body = TestClient(create_app(HubRegistry())).get("/api/v1/sessions").json()
    finally:
        get_settings.cache_clear()
    assert body["active"] == [] and body["stored"] == []
    assert body["stored_error"] == "database unavailable"
