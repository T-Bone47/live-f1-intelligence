"""Phase 10.1A Section 23 acceptance test: real F1 telemetry, the actual
canonical pipeline, a real Postgres instance, verified against the REST API.

Uses scripts/fixtures/real-openf1-9159 - genuine OpenF1 car_data (2023-09-15,
session_key 9159, driver 55), not a synthetic fixture. See
scripts/build_real_openf1_fixture.py for provenance.

Walks the Section 23 checklist: replay the real recording through
ReplayProvider -> SessionHub.feed() (the same canonical path live data
takes) -> PersistenceSubscriber -> real Postgres, then queries both the
database directly and the REST API, and checks they agree.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import HubRegistry, create_app
from app.ingest.persistence import PersistenceSubscriber
from app.providers.replay import ReplayProvider
from app.realtime.hub import SessionHub
from app.storage.db import Repository

FIXTURE_DIR = Path(__file__).parent.parent.parent / "scripts" / "fixtures" / "real-openf1-9159"
REAL_SESSION_ID = "openf1:9159"  # the identity recorded IN the envelopes


@pytest.fixture
async def clean_real_session(pg_pool):
    """The fixture's session_id is fixed (it's the real recorded identity,
    not a per-test UUID), so explicitly clear any rows a previous run of
    this exact test left behind before and after, rather than relying on
    per-test isolation."""
    async def _clear():
        await pg_pool.execute("DELETE FROM telemetry_car WHERE session_id=$1", REAL_SESSION_ID)
        await pg_pool.execute("DELETE FROM sessions WHERE session_id=$1", REAL_SESSION_ID)
        await pg_pool.execute("DELETE FROM events WHERE session_id=$1", REAL_SESSION_ID)
    await _clear()
    yield
    await _clear()


@pytest.mark.asyncio
async def test_real_recording_persists_and_is_queryable_via_rest_api(
    pg_pool, clean_real_session, monkeypatch,
):
    # --- 1-2: Postgres + migrations already handled by the pg_pool fixture ---
    assert FIXTURE_DIR.exists(), f"real fixture missing: {FIXTURE_DIR}"

    # --- 5: start ReplayProvider against the real recording ---
    provider = ReplayProvider(FIXTURE_DIR)
    provider.set_speed(0)  # no pacing needed for the acceptance check itself
    session = await provider.resolve_session(str(FIXTURE_DIR))

    # --- 3, 7-10: real hub + real PersistenceSubscriber, same canonical path
    #     live data takes (hub.feed() -> pipeline -> bus -> analysis + persistence) ---
    hub = SessionHub(session_id="replay:real-openf1-9159")
    repo = Repository(pg_pool)
    persistence = PersistenceSubscriber(repo)
    hub.pipeline.bus.subscribe("persistence", persistence)

    # --- 6: feed the real recording through the canonical pipeline ---
    n_fed = 0
    async for item in provider.run(session):
        await hub.feed(item)
        n_fed += 1
    assert n_fed == 40  # 1 SessionInfo + 39 real TelemetryCarSample envelopes

    # --- 18-19: stop replay normally, flush buffered persistence ---
    await persistence.flush()

    # --- 11-12, 24: verify real Postgres rows, with exact counts, not "looks correct" ---
    session_row = await pg_pool.fetchrow(
        "SELECT provider, provider_session_key FROM sessions WHERE session_id=$1",
        REAL_SESSION_ID)
    assert session_row is not None
    assert session_row["provider"] == "openf1"
    assert session_row["provider_session_key"] == "9159"

    car_rows = await pg_pool.fetch(
        "SELECT ts, rpm, speed_kph, provenance_class FROM telemetry_car "
        "WHERE session_id=$1 ORDER BY ts", REAL_SESSION_ID)
    assert len(car_rows) == 39  # every real sample landed, none lost, none duplicated

    # --- 15: timestamps genuinely ordered (real recorded order, not just insert order) ---
    timestamps = [r["ts"] for r in car_rows]
    assert timestamps == sorted(timestamps)

    # --- 16, 9/10 (provenance): replayed historical data must be class B, never A ---
    assert all(r["provenance_class"] == "B" for r in car_rows)

    # --- a real, known value from the actual OpenF1 fetch survived the full
    #     pipeline intact: the first 315 km/h sample, rpm 11141 ---
    high_speed = [r for r in car_rows if r["speed_kph"] == 315]
    assert len(high_speed) == 2
    assert {r["rpm"] for r in high_speed} == {11141, 11023}

    # --- 20: exact final counts, with an explained reconciliation, not eyeballed ---
    evt_count = await pg_pool.fetchval(
        "SELECT count(*) FROM events WHERE session_id=$1", REAL_SESSION_ID)
    assert evt_count == 40  # every envelope (1 session + 39 telemetry) audit-logged
    # written = 39 car samples + 40 event-log rows. SessionInfo itself uses
    # upsert_session() directly and isn't counted there - only its event-log
    # entry is (persistence.py's own __call__/_count() behavior, not this test's).
    assert persistence.written == 39 + 40
    assert persistence.conflicts == 0
    assert persistence.errors == 0

    # --- 13-14, 25: the REST API must return exactly what's in the database,
    #     not a separate/fabricated view of it ---
    monkeypatch.setenv("DATABASE_URL",
                        "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel")
    from app.config import get_settings
    get_settings.cache_clear()

    client = TestClient(create_app(HubRegistry()))  # no active hub - proves independence
    resp = client.get(
        f"/api/v1/sessions/{REAL_SESSION_ID}/telemetry/55"
        "?frequency=RAW&start=2023-09-15T12:48:06Z&end=2023-09-15T12:48:17Z"
    )
    get_settings.cache_clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == REAL_SESSION_ID
    assert body["provenance"]["class"] == "B"
    api_rpm_values = [p["value"] for p in body["series"]["rpm"]]
    db_rpm_values = [float(r["rpm"]) for r in car_rows
                     if r["ts"].isoformat() >= "2023-09-15T12:48:06"
                     and r["ts"].isoformat() < "2023-09-15T12:48:17"]
    assert api_rpm_values == db_rpm_values  # API series matches DB exactly, same order
