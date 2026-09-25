"""GET /api/v1/sessions/{sid}/attribution on REAL data through a REAL Postgres.

Seeds the Singapore pair (raw OpenF1 rows -> mapper -> Repository), calls
the route, and requires its attribution to equal the engine run directly on
the same rows: the lineage fixture -> DB -> API adds nothing and loses
nothing. Skips without Postgres (TEST_DATABASE_URL) or without the fixture.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis.attribution import attribute_comparison, report_to_dict
from app.analysis.delta_analysis import analyze_delta
from app.analysis.lap_comparison import compare_driver_laps
from app.api import HubRegistry, create_app
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Provenance, SessionInfo
from app.providers.openf1.mapping import to_car_sample, to_lap
from app.storage.db import Repository

ROOT = Path(__file__).parent.parent.parent
FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
DB = os.environ.get("TEST_DATABASE_URL",
                    "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel")
SOURCE = "Wikipedia, 2023 Singapore Grand Prix: course length 4.940 km"

pytestmark = pytest.mark.skipif(not (FIXTURE / "meta.json").exists(),
                                reason="no real two-driver fixture")


def _real(sid):
    meta = json.loads((FIXTURE / "meta.json").read_text())
    laps, samples = {}, {}
    for d in (meta["driver_a"], meta["driver_b"]):
        laps[d], _ = to_lap(json.loads((FIXTURE / f"driver_{d}_lap.json").read_text()), sid)
        rows = json.loads((FIXTURE / f"driver_{d}_car_data.json").read_text())
        samples[d] = sorted((to_car_sample(r, sid) for r in rows), key=lambda s: s.ts)
    return meta, laps, samples


@pytest.fixture
async def seeded(pg_pool):
    sid = f"pytest:attr:{uuid.uuid4().hex[:12]}"
    meta, laps, samples = _real(sid)
    repo = Repository(pg_pool)
    await repo.upsert_session(SessionInfo(
        session_id=sid, provider=ProviderName.OPENF1, provider_session_key="9161",
        provenance=Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.B)))
    for d in laps:
        await repo.insert_lap(laps[d])
        await repo.insert_car_samples_bulk([
            (s.session_id, s.driver_number, s.ts, s.rpm, s.speed_kph, s.gear, s.throttle_pct,
             s.brake_pct, s.drs, s.provenance.provenance_class.value) for s in samples[d]])
    yield sid, meta, laps, samples
    for table in ("telemetry_car", "laps", "sessions"):
        await pg_pool.execute(f"DELETE FROM {table} WHERE session_id=$1", sid)


def _client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB)
    from app.config import get_settings
    get_settings.cache_clear()
    return TestClient(create_app(HubRegistry()))


def _url(sid, meta, **over):
    q = {"driver_a": meta["driver_a"], "lap_a": meta["lap_a"], "driver_b": meta["driver_b"],
             "lap_b": meta["lap_b"], "lap_length_m": meta["lap_length_m"], "lap_length_source": SOURCE}
    q.update(over)
    return f"/api/v1/sessions/{sid}/attribution?" + "&".join(f"{k}={v}" for k, v in q.items())


async def test_route_equals_the_engine_on_the_same_real_rows(seeded, monkeypatch):
    sid, meta, laps, samples = seeded
    a, b = meta["driver_a"], meta["driver_b"]
    try:
        resp = _client(monkeypatch).get(_url(sid, meta))
    finally:
        from app.config import get_settings
        get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    cmp = compare_driver_laps(laps[a], samples[a], None, laps[b], samples[b], None,
                              lap_length_m=meta["lap_length_m"])
    direct = report_to_dict(attribute_comparison(analyze_delta(cmp), laps[a], laps[b]))
    assert body["attribution"] == json.loads(json.dumps(direct))
    assert body["alignment"]["mode"] == "NORMALIZED_DISTANCE"
    assert body["lap_length"] == {"m": meta["lap_length_m"], "source": SOURCE}
    assert body["context_pack"]["pack"] == "lap_attribution_v1"


async def test_route_refuses_to_invent_inputs(seeded, monkeypatch, pg_pool):
    sid, meta, _laps, _samples = seeded
    try:
        client = _client(monkeypatch)
        assert client.get(_url(sid, meta, lap_length_source="%20")).status_code == 422
        assert client.get(_url(sid, meta, lap_length_m=0)).status_code == 422
        assert client.get(_url(sid, meta, lap_a=999)).status_code == 404
        await pg_pool.execute("UPDATE laps SET duration_s=NULL WHERE session_id=$1 "
                              "AND driver_number=$2", sid, meta["driver_a"])
        r = client.get(_url(sid, meta))
        assert r.status_code == 422 and "no duration" in r.text  # no 3-minute window guessed
    finally:
        from app.config import get_settings
        get_settings.cache_clear()
