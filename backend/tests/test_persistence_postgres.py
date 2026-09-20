"""PersistenceSubscriber against a real Postgres instance.

Skips (via the pg_pool fixture) rather than fails when no test database is
reachable - persistence correctness genuinely needs a real database, not a
mock, but the rest of the suite shouldn't break over its absence.

These specifically cover a real bug found while auditing Phase 10.1A: the
bulk telemetry/event insert paths used asyncpg's executemany(), which
cannot RETURNING, so flush() always reported the full attempted batch size
as "written" even when rows were silently absorbed by ON CONFLICT DO
NOTHING - and a genuine event-log insert failure was counted as written
too, since the increment sat outside the try/except that caught it.

Each test uses a fresh, unique session_id (session_sid fixture) so runs
never collide with leftover rows from a previous run against the same
long-lived local Postgres instance.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.enums import ProvenanceClass, ProviderName
from app.core.events import make_envelope
from app.core.models import Provenance, TelemetryCarSample, TelemetryLocationSample
from app.ingest.persistence import PersistenceSubscriber
from app.storage.db import Repository

PROV = Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.A)


@pytest.fixture
def session_sid():
    return f"pytest:persistence:{uuid.uuid4()}"


def _car_envelope(session_id: str, driver: int, ts: datetime):
    sample = TelemetryCarSample(
        session_id=session_id, driver_number=driver, ts=ts,
        rpm=11000, speed_kph=210, gear=6, throttle_pct=80.0, brake_pct=0.0,
        drs=1, provenance=PROV,
    )
    return make_envelope(event_type="TELEMETRY_CAR", session_id=session_id,
                          model=sample, source="test", dedupe_key=None,
                          driver_number=driver)


def _loc_envelope(session_id: str, driver: int, ts: datetime):
    sample = TelemetryLocationSample(
        session_id=session_id, driver_number=driver, ts=ts,
        x=100.0, y=200.0, z=0.0, provenance=PROV,
    )
    return make_envelope(event_type="TELEMETRY_LOCATION", session_id=session_id,
                          model=sample, source="test", dedupe_key=None,
                          driver_number=driver)


@pytest.mark.asyncio
async def test_flush_batches_rather_than_writing_immediately(pg_pool, session_sid):
    sub = PersistenceSubscriber(Repository(pg_pool))
    ts = datetime.now(UTC)

    await sub(_car_envelope(session_sid, 1, ts))
    row = await pg_pool.fetchrow(
        "SELECT 1 FROM telemetry_car WHERE session_id=$1", session_sid)
    assert row is None  # buffered, not yet flushed

    await sub.flush()
    row = await pg_pool.fetchrow(
        "SELECT 1 FROM telemetry_car WHERE session_id=$1", session_sid)
    assert row is not None
    # Every envelope also produces one audit event-log row (persistence.py
    # appends to _evt_buf unconditionally) - 1 car sample + 1 event log row.
    assert sub.written == 2
    assert sub.conflicts == 0


@pytest.mark.asyncio
async def test_flush_counts_duplicates_as_conflicts_not_written(pg_pool, session_sid):
    sub = PersistenceSubscriber(Repository(pg_pool))
    ts = datetime.now(UTC)

    await sub(_car_envelope(session_sid, 1, ts))
    await sub(_car_envelope(session_sid, 1, ts))  # identical (session, driver, ts) key
    await sub.flush()

    car_count = await pg_pool.fetchval(
        "SELECT count(*) FROM telemetry_car WHERE session_id=$1", session_sid)
    assert car_count == 1  # the UNIQUE constraint, not application logic, enforced this
    evt_count = await pg_pool.fetchval(
        "SELECT count(*) FROM events WHERE session_id=$1", session_sid)
    assert evt_count == 2  # each make_envelope() call gets its own event_id - no conflict there
    # written = 1 car + 2 event-log; conflicts = the 1 duplicate car sample
    assert sub.written == 3
    assert sub.conflicts == 1


@pytest.mark.asyncio
async def test_auto_flush_triggers_at_batch_size(pg_pool, session_sid, monkeypatch):
    import app.ingest.persistence as persistence_mod
    monkeypatch.setattr(persistence_mod, "_BATCH_SIZE", 3)

    sub = PersistenceSubscriber(Repository(pg_pool))
    ts = datetime.now(UTC)

    for i in range(3):
        await sub(_car_envelope(session_sid, i, ts))  # 3rd call crosses the patched threshold

    count = await pg_pool.fetchval(
        "SELECT count(*) FROM telemetry_car WHERE session_id=$1", session_sid)
    assert count == 3  # written without an explicit flush() call


@pytest.mark.asyncio
async def test_location_samples_also_flush_and_count_correctly(pg_pool, session_sid):
    sub = PersistenceSubscriber(Repository(pg_pool))
    ts = datetime.now(UTC)

    await sub(_loc_envelope(session_sid, 1, ts))
    await sub.flush()

    assert sub.written >= 1
    row = await pg_pool.fetchrow(
        "SELECT x, y, z FROM telemetry_location WHERE session_id=$1", session_sid)
    assert row is not None
    assert row["x"] == 100.0


@pytest.mark.asyncio
async def test_event_log_failure_is_not_counted_as_written(pg_pool, session_sid, monkeypatch):
    """The bug: self.written += len(evt) sat outside the try/except, so a
    genuine event-log insert failure still got counted as written."""
    repo = Repository(pg_pool)
    sub = PersistenceSubscriber(repo)
    ts = datetime.now(UTC)

    async def boom(payloads):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(repo, "insert_events_bulk", boom)

    await sub(_car_envelope(session_sid, 1, ts))
    await sub.flush()

    # The car sample itself still persisted (independent buffer/insert path);
    # only the event-log write failed.
    car_count = await pg_pool.fetchval(
        "SELECT count(*) FROM telemetry_car WHERE session_id=$1", session_sid)
    assert car_count == 1
    evt_count = await pg_pool.fetchval(
        "SELECT count(*) FROM events WHERE session_id=$1", session_sid)
    assert evt_count == 0
    assert sub.written == 1  # the car sample only - NOT the failed event-log row
    assert sub.errors == 1
