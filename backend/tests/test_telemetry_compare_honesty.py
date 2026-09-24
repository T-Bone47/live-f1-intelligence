"""/telemetry/compare must not claim an alignment it does not compute.

Root cause (found during Phase 10.2 real-data validation): with ?lap=N the
route returned alignment.mode="normalized_lap_progress", valid=true, but
?lap= only narrows each driver's query to that driver's own lap time
window. No distance integration or normalization happens anywhere in the
API module - the series are two independent time-indexed traces. The
distance-synchronized comparison exists (app.analysis.lap_comparison) but
is not routed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import HubRegistry, create_app
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Provenance, SessionInfo
from app.storage.db import Repository

DB = "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel"


@pytest.fixture
async def seeded(pg_pool):
    sid = f"pytest:compare:{uuid.uuid4()}"
    await Repository(pg_pool).upsert_session(SessionInfo(
        session_id=sid, provider=ProviderName.OPENF1, provider_session_key="x",
        provenance=Provenance(provider=ProviderName.OPENF1,
                              provenance_class=ProvenanceClass.B)))
    t0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    for d, start_offset in ((1, 0), (2, 300)):  # laps at different wall-clock times
        start = t0 + timedelta(seconds=start_offset)
        await pg_pool.execute(
            "INSERT INTO laps(session_id, driver_number, lap_number, started_at, duration_s,"
            " provenance_class) VALUES($1,$2,5,$3,10.0,'B')", sid, d, start)
        for k in range(11):
            await pg_pool.execute(
                "INSERT INTO telemetry_car(session_id, driver_number, ts, speed_kph,"
                " provenance_class) VALUES($1,$2,$3,200,'B')",
                sid, d, start + timedelta(seconds=k))
    yield sid
    for table in ("telemetry_car", "laps", "sessions"):
        await pg_pool.execute(f"DELETE FROM {table} WHERE session_id=$1", sid)


async def test_lap_compare_does_not_claim_distance_alignment(seeded, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB)
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        resp = TestClient(create_app(HubRegistry())).get(
            f"/api/v1/sessions/{seeded}/telemetry/compare?drivers=1,2&lap=5")
    finally:
        get_settings.cache_clear()

    assert resp.status_code == 200
    alignment = resp.json()["alignment"]
    assert alignment["mode"] != "normalized_lap_progress"
    assert alignment["valid"] is False
    assert "not distance-aligned" in alignment["note"]
    # the series really are per-driver time windows: both drivers' data came
    # back even though their laps ran 300 real seconds apart
    assert set(resp.json()["series"]) == {"1", "2"}
