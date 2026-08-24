"""Pipeline behavior: normalization dispatch, dedupe, malformed isolation,
timestamp preservation, replay passthrough."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.events import Envelope
from app.ingest.pipeline import IngestPipeline
from app.providers.base import Channel, RawItem

FIXTURES = Path(__file__).parent / "fixtures" / "openf1"
SESSION = "openf1:11353"


def load(name: str) -> list[dict]:
    # utf-8-sig: tolerate editor/tooling BOMs on Windows
    return json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))


def make_pipeline() -> tuple[IngestPipeline, list[Envelope]]:
    bus_published: list[Envelope] = []

    async def sink(env: Envelope) -> None:
        bus_published.append(env)

    p = IngestPipeline(session_id=SESSION)
    p.bus.subscribe("test", sink)
    return p, bus_published


NOW = datetime(2026, 8, 23, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def frozen_now(monkeypatch):
    dt = NOW

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ARG003
            return dt

    monkeypatch.setattr("app.ingest.pipeline.datetime", FakeDT)
    return dt


async def test_lap_item_produces_lap_and_three_sectors(frozen_now) -> None:
    p, published = make_pipeline()
    row = load("laps.json")[0]
    n = await p.process(RawItem(Channel.LAP, row, frozen_now, "B"))
    assert n == 4  # 1 lap + 3 sectors
    types = [e.event_type for e in published]
    assert types.count("sector.recorded") == 3
    assert types[0] == "lap.completed"
    # timestamp preservation
    assert published[0].source_timestamp == datetime(2026, 8, 23, 13, 3, 28, 567000,
                                                    tzinfo=timezone.utc)


async def test_duplicate_detection(frozen_now) -> None:
    p, published = make_pipeline()
    item = RawItem(Channel.LAP, load("laps.json")[0], frozen_now, "B")
    assert await p.process(item) == 4
    assert await p.process(item) == 0  # duplicate suppressed
    assert await p.process(RawItem(Channel.LAP, dict(load("laps.json")[0]), frozen_now, "B")) == 0
    # 4 envelopes per re-delivered lap item (lap + 3 sectors)
    assert p.quality.duplicate_events == 8


async def test_malformed_isolated_not_fatal(frozen_now) -> None:
    p, _published = make_pipeline()
    bad = RawItem(Channel.LAP, {"garbage": True}, frozen_now, "B")
    good = RawItem(Channel.WEATHER, load("weather.json")[0], frozen_now, "A")
    assert await p.process(bad) == 0
    assert await p.process(good) == 1
    assert p.quality.malformed_events == 1
    assert p.quality.channel_counts.get("weather") == 1


async def test_unknown_channel_rejected(frozen_now) -> None:
    p, _ = make_pipeline()
    n = await p.process(RawItem(Channel.TEAM_RADIO, {"x": 1}, frozen_now, "A"))
    assert n == 0 and p.quality.malformed_events == 1


async def test_stint_full_refresh_dedupes(frozen_now) -> None:
    p, published = make_pipeline()
    for stint in load("stints.json"):
        await p.process(RawItem(Channel.STINT, stint, None, "B"))
    first_count = len([e for e in published if e.event_type == "tyre.stint_recorded"])
    assert first_count == 4
    # re-poll same stints (historical full refresh pattern)
    for stint in load("stints.json"):
        await p.process(RawItem(Channel.STINT, stint, None, "B"))
    assert len([e for e in published if e.event_type == "tyre.stint_recorded"]) == 4


async def test_rcm_dedupe_via_content_hash(frozen_now) -> None:
    p, published = make_pipeline()
    rcm_rows = load("race_control.json")[:3]
    for row in rcm_rows:
        await p.process(RawItem(Channel.RACE_CONTROL, row, frozen_now, "B"))
        await p.process(RawItem(Channel.RACE_CONTROL, dict(row), frozen_now, "B"))
    assert len([e for e in published if e.event_type == "rcm.message"]) == 3
    assert p.quality.duplicate_events == 3


async def test_driver_emits_driver_and_team(frozen_now) -> None:
    p, published = make_pipeline()
    await p.process(RawItem(Channel.DRIVER_LIST, load("drivers.json")[0], frozen_now, "B"))
    types = {e.event_type for e in published}
    assert "driver.detected" in types and "team.detected" in types


async def test_replay_passthrough_preserves_envelope(frozen_now) -> None:
    """Recorded envelope re-emitted through the pipeline stays byte-equivalent."""
    p, published = make_pipeline()
    # first pass: live-ish ingestion
    await p.process(RawItem(Channel.CAR_DATA, load("car_data.json")[0], frozen_now, "A"))
    original = published[-1]

    replay_item = RawItem(
        Channel.SESSION_META,
        {"__envelope": json.loads(original.model_dump_json())},
        frozen_now,
        "A",
    )
    p2, published2 = make_pipeline()
    n = await p2.process(replay_item)
    assert n == 1
    round_tripped = published2[-1]
    assert round_tripped.event_type == original.event_type
    assert round_tripped.payload == original.payload
    assert round_tripped.dedupe_key == original.dedupe_key


async def test_latency_measured_live_only_flag(frozen_now) -> None:
    p, _ = make_pipeline()
    # synthetic row with a controlled source timestamp (13:59:58)
    row = dict(load("weather.json")[0])
    row["date"] = "2026-08-23T13:59:58+00:00"
    await p.process(RawItem(Channel.WEATHER, row, frozen_now, "A"))
    lat_all = p.quality._latency_stats(p.quality._latency)
    assert lat_all["samples"] == 1
    assert lat_all["avg_s"] == pytest.approx(2.0, abs=0.01)  # NOW(14:00) - 13:59:58
    lat_live = p.quality._latency_stats(p.quality._latency_live_only)
    assert lat_live["samples"] == 1  # class A counted in live-only stats too
