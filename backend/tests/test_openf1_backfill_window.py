"""OpenF1 historical backfill window (Phase 11).

Real finding (2026 Dutch GP race, session 11353): OpenF1 publishes the starting
grid as position rows at 12:06:50Z, 53 minutes before date_start (13:00Z). The
backfill seeded every cursor at date_start - 45 min, so the grid never reached
the recording, and a car that did not change position (the leader) had no
position for its first 36 minutes. Session-keyed ranged channels must start
early enough to include it; high-rate telemetry windows keep the tight seed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import get_settings
from app.core.enums import ProvenanceClass, ProviderName, SessionStatus, SessionType
from app.core.models import Provenance, SessionInfo
from app.providers.base import Channel
from app.providers.openf1 import provider as provider_mod
from app.providers.openf1.provider import OpenF1Provider

START = datetime(2026, 8, 23, 13, 0, tzinfo=UTC)
END = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)
GRID_TS = datetime(2026, 8, 23, 12, 6, 50, 962000, tzinfo=UTC)   # real, 53 min early


def _ts(t: datetime) -> str:
    return t.isoformat()


class FakeClient:
    """Answers like OpenF1: session-keyed rows with date >= since (and < until)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.rows = {
            "position": [
                {"session_key": 11353, "meeting_key": 1292, "driver_number": 1,
                 "date": _ts(GRID_TS), "position": 1},
                {"session_key": 11353, "meeting_key": 1292, "driver_number": 63,
                 "date": _ts(START + timedelta(minutes=4)), "position": 3},
            ],
        }

    def _range(self, name: str, since: str, until: str | None) -> list[dict]:
        self.calls.append((name, since))
        lo = datetime.fromisoformat(since)
        hi = datetime.fromisoformat(until) if until else None
        return [r for r in self.rows.get(name, [])
                if datetime.fromisoformat(r["date"]) >= lo
                and (hi is None or datetime.fromisoformat(r["date"]) < hi)]

    async def drivers(self, sk):
        return []

    async def stints(self, sk):
        return []

    async def laps_since(self, sk, since, until=None):
        self.calls.append(("laps", since))
        return []

    async def car_data_since(self, sk, since, until=None):
        return self._range("car_data", since, until)

    async def location_since(self, sk, since, until=None):
        return self._range("location", since, until)

    async def pits_since(self, sk, since, until=None):
        return self._range("pit", since, until)

    async def weather_since(self, sk, since, until=None):
        return self._range("weather", since, until)

    async def race_control_since(self, sk, since, until=None):
        return self._range("race_control", since, until)

    async def positions_since(self, sk, since, until=None):
        return self._range("position", since, until)

    async def intervals_since(self, sk, since, until=None):
        return self._range("intervals", since, until)


def _session() -> SessionInfo:
    return SessionInfo(
        session_id="openf1:11353", provider=ProviderName.OPENF1, provider_session_key="11353",
        year=2026, session_type=SessionType.RACE, date_start=START, date_end=END,
        status=SessionStatus.FINISHED,
        provenance=Provenance(provider=ProviderName.OPENF1, source_timestamp=START,
                              provenance_class=ProvenanceClass.B))


async def _run(monkeypatch) -> tuple[list, FakeClient]:
    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(provider_mod.asyncio, "sleep", no_sleep)
    client = FakeClient()
    prov = OpenF1Provider(client, get_settings())   # type: ignore[arg-type]
    items = [item async for item in prov.run(_session())]
    return items, client


@pytest.mark.asyncio
async def test_backfill_includes_the_starting_grid_published_before_the_session(monkeypatch):
    items, _client = await _run(monkeypatch)
    dates = sorted(i.payload["date"] for i in items if i.channel is Channel.POSITION)
    assert _ts(GRID_TS) in dates, "starting-grid position row was not fetched"


@pytest.mark.asyncio
async def test_telemetry_windows_keep_the_tight_seed(monkeypatch):
    _items, client = await _run(monkeypatch)
    first_car = min(datetime.fromisoformat(s) for n, s in client.calls if n == "car_data")
    assert first_car >= START - provider_mod.LIVE_WINDOW_BEFORE
