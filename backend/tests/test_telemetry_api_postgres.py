"""GET /telemetry/{driver}'s provenance field, against a real Postgres.

Covers a real bug found while auditing Phase 10.1A: the endpoint derived
its response-level provenance.class from hub_active(session_id) - "is any
hub registered for this id" - which cannot distinguish a live hub from a
replay hub. A replay actively running for a session would make its stored
(correctly class-B) telemetry get reported back as class A ("direct live
observation") in the API response, even though the actual rows were never
relabeled. Fixed to read provenance_class from the rows actually returned.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import HubRegistry, create_app
from app.realtime.hub import SessionHub


@pytest.fixture
def session_sid():
    return f"pytest:telemetry-api:{uuid.uuid4()}"


async def _insert_car_sample(pool, session_id: str, driver: int, ts: datetime,
                              provenance_class: str):
    await pool.execute(
        """INSERT INTO telemetry_car(session_id, driver_number, ts, rpm,
           speed_kph, gear, throttle_pct, brake_pct, drs, provenance_class)
           VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
        session_id, driver, ts, 11000, 210, 6, 80.0, 0.0, 1, provenance_class,
    )


@pytest.mark.asyncio
async def test_telemetry_provenance_reflects_stored_data_not_hub_activity(
    pg_pool, session_sid, monkeypatch,
):
    """The exact regression: register an ACTIVE hub for this session_id
    (simulating a replay in progress) while the stored telemetry is
    genuinely class B. The response must still say B - hub activity must
    not override what's actually in the database."""
    monkeypatch.setenv("DATABASE_URL",
                        "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel")
    from app.config import get_settings
    get_settings.cache_clear()

    ts = datetime.now(timezone.utc)
    await _insert_car_sample(pg_pool, session_sid, 44, ts, "B")

    registry = HubRegistry()
    registry.register(SessionHub(session_sid))  # active hub - old bug's trigger

    app = create_app(registry)
    client = TestClient(app)
    resp = client.get(f"/api/v1/sessions/{session_sid}/telemetry/44")

    get_settings.cache_clear()

    assert resp.status_code == 200
    assert resp.json()["provenance"]["class"] == "B"


@pytest.mark.asyncio
async def test_telemetry_provenance_reports_a_for_class_a_data(
    pg_pool, session_sid, monkeypatch,
):
    monkeypatch.setenv("DATABASE_URL",
                        "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel")
    from app.config import get_settings
    get_settings.cache_clear()

    ts = datetime.now(timezone.utc)
    await _insert_car_sample(pg_pool, session_sid, 44, ts, "A")

    app = create_app(HubRegistry())  # no hub registered at all this time
    client = TestClient(app)
    resp = client.get(f"/api/v1/sessions/{session_sid}/telemetry/44")

    get_settings.cache_clear()

    assert resp.status_code == 200
    assert resp.json()["provenance"]["class"] == "A"
