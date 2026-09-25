"""GET /api/v1/sessions/{sid}/evidence/lap-comparison - REAL rows, REAL Postgres.

The route's bytes must EQUAL the builder run directly on the same rows
(fixture -> DB -> API adds and loses nothing), repeat requests must be
byte-identical, bad requests must fail explicitly, and the existing routes
must keep working. Skips without Postgres (TEST_DATABASE_URL) or fixture.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.api import HubRegistry, create_app
from app.core.enums import ProvenanceClass, ProviderName, SessionType
from app.core.models import Provenance, SessionInfo
from app.evidence import SourceInfo, build_lap_comparison_evidence, to_canonical_json
from app.providers.openf1.mapping import to_car_sample, to_lap
from app.storage.db import Repository

ROOT = Path(__file__).parent.parent.parent
FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
DB = os.environ.get("TEST_DATABASE_URL",
                    "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel")
ROUTE = "/api/v1/sessions/{sid}/evidence/lap-comparison"

pytestmark = pytest.mark.skipif(not (FIXTURE / "meta.json").exists(),
                                reason="no real two-driver fixture")


@pytest.fixture
async def seeded(pg_pool):
    meta = json.loads((FIXTURE / "meta.json").read_text())
    sid = f"pytest:ev:{uuid.uuid4().hex[:12]}"
    laps, samples = {}, {}
    for d in (meta["driver_a"], meta["driver_b"]):
        laps[d], _ = to_lap(json.loads((FIXTURE / f"driver_{d}_lap.json").read_text()), sid)
        rows = json.loads((FIXTURE / f"driver_{d}_car_data.json").read_text())
        samples[d] = sorted((to_car_sample(r, sid) for r in rows), key=lambda s: s.ts)
    repo = Repository(pg_pool)
    await repo.upsert_session(SessionInfo(
        session_id=sid, provider=ProviderName.OPENF1, provider_session_key="9161",
        session_type=SessionType.QUALIFYING, year=meta["year"],
        circuit_short_name=meta["circuit_short_name"],
        provenance=Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.B)))
    for d, lap in laps.items():
        await repo.insert_lap(lap)
        await repo.insert_car_samples_bulk([
            (s.session_id, s.driver_number, s.ts, s.rpm, s.speed_kph, s.gear, s.throttle_pct,
             s.brake_pct, s.drs, s.provenance.provenance_class.value) for s in samples[d]])
    yield sid, meta, laps, samples
    for table in ("telemetry_car", "laps", "sessions"):
        await pg_pool.execute(f"DELETE FROM {table} WHERE session_id=$1", sid)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB)
    from app.config import get_settings
    get_settings.cache_clear()
    yield TestClient(create_app(HubRegistry()))
    get_settings.cache_clear()


def _url(sid, meta, **over):
    q = {"driver_a": meta["driver_a"], "lap_a": meta["lap_a"], "driver_b": meta["driver_b"],
             "lap_b": meta["lap_b"], "lap_length_m": meta["lap_length_m"],
             "lap_length_source": meta["lap_length_source"]}
    q.update(over)
    return ROUTE.format(sid=sid) + "?" + urlencode(q)


async def test_route_bytes_equal_the_builder_on_the_same_real_rows(seeded, client):
    sid, meta, laps, samples = seeded
    resp = client.get(_url(sid, meta))
    assert resp.status_code == 200, resp.text
    a, b = meta["driver_a"], meta["driver_b"]
    direct = build_lap_comparison_evidence(
        laps[a], samples[a], laps[b], samples[b], lap_length_m=meta["lap_length_m"],
        lap_length_source=meta["lap_length_source"],
        source=SourceInfo(session_id=sid, provider="openf1", session_type="Qualifying",
                          season=meta["year"], event=None, circuit=meta["circuit_short_name"]))
    assert resp.content == to_canonical_json(direct)
    assert resp.headers["X-Evidence-Contract"] == "evidence_v1"
    assert resp.headers["X-Evidence-Id"] == direct.evidence_id
    assert "db;dur=" in resp.headers["Server-Timing"]
    assert client.get(_url(sid, meta)).content == resp.content  # deterministic


async def test_route_fails_explicitly_never_fabricates(seeded, client, pg_pool):
    sid, meta, _laps, _samples = seeded
    cases = {
        "missing lap length": (ROUTE.format(sid=sid) + "?" + urlencode(
            {"driver_a": 55, "lap_a": 19, "driver_b": 63, "lap_b": 16,
             "lap_length_source": "x"}), 422),
        "zero lap length": (_url(sid, meta, lap_length_m=0), 422),
        "blank source": (_url(sid, meta, lap_length_source=" "), 422),
        "invalid driver": (_url(sid, meta, driver_a=0), 422),
        "invalid lap": (_url(sid, meta, lap_a=0), 422),
        "same lap twice": (_url(sid, meta, driver_b=meta["driver_a"], lap_b=meta["lap_a"]), 422),
        "unsupported contract": (_url(sid, meta, contract_version="evidence_v2"), 422),
        "unknown lap": (_url(sid, meta, lap_a=99), 404),
        "unknown driver": (_url(sid, meta, driver_a=7), 404),
        "unknown session": (_url("pytest:ev:none", meta), 404),
    }
    for name, (url, code) in cases.items():
        assert client.get(url).status_code == code, name
    await pg_pool.execute("UPDATE laps SET duration_s=NULL WHERE session_id=$1 AND "
                          "driver_number=$2", sid, meta["driver_a"])
    r = client.get(_url(sid, meta))
    assert r.status_code == 422 and "no duration" in r.text


async def test_existing_routes_keep_their_contracts(seeded, client):
    sid, meta, *_ = seeded
    q = urlencode({"driver_a": meta["driver_a"], "lap_a": meta["lap_a"],
                       "driver_b": meta["driver_b"], "lap_b": meta["lap_b"],
                       "lap_length_m": meta["lap_length_m"],
                       "lap_length_source": meta["lap_length_source"]})
    att = client.get(f"/api/v1/sessions/{sid}/attribution?{q}")
    assert att.status_code == 200
    assert set(att.json()) == {"session_id", "drivers", "lap_length", "alignment",
                               "attribution", "context_pack"}
    # no ?lap=: that route uses ONE lap number for both drivers (#63 has no lap 19)
    cmp = client.get(f"/api/v1/sessions/{sid}/telemetry/compare?drivers=55,63")
    assert cmp.status_code == 200 and cmp.json()["alignment"]["valid"] is False
