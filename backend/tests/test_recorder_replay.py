"""Recorder <-> ReplayProvider round-trip: the replay-compatibility proof."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.events import Envelope
from app.ingest.pipeline import IngestPipeline
from app.ingest.recorder import Recorder
from app.providers.base import Channel, RawItem
from app.providers.replay import ReplayProvider

FIXTURES = Path(__file__).parent / "fixtures" / "openf1"


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))


def _env(i: int, ts: datetime) -> Envelope:
    from app.core.enums import ProvenanceClass

    return Envelope(
        event_type="weather.updated",
        session_id="openf1:test",
        driver_number=None,
        source="openf1",
        source_timestamp=ts,
        ingestion_timestamp=ts,
        provenance_class=ProvenanceClass.A,
        dedupe_key=f"wx:{i}",
        payload={"model": {"type": "WeatherPoint",
                           "session_id": "openf1:test", "ts": ts.isoformat(),
                           "air_temp_c": 20.0 + i, "track_temp_c": None,
                           "humidity_pct": None, "pressure_hpa": None,
                           "rainfall": False, "wind_direction_deg": None,
                           "wind_speed_mps": None,
                           "provenance": {"provider": "openf1",
                                          "source_timestamp": ts.isoformat(),
                                          "ingestion_timestamp": ts.isoformat(),
                                          "provenance_class": "A"}}},
    )


@pytest.fixture()
def recording(tmp_path: Path) -> Path:
    rec = Recorder(tmp_path / "recordings", "test-recording")
    rec.write_meta({"session_key": "test"}, "openf1")
    base = datetime(2026, 8, 23, 13, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        rec.write(_env(i, base + timedelta(seconds=i * 10)))
    rec.finalize()
    return rec.dir


async def test_record_then_replay_round_trip(recording: Path) -> None:
    provider = ReplayProvider(recording)
    provider.set_speed(0)  # max speed
    session = await provider.resolve_session(str(recording))
    assert session.session_id.startswith("replay:")

    pipeline = IngestPipeline(session_id=session.session_id)
    seen: list[Envelope] = []

    async def sink(env: Envelope) -> None:
        seen.append(env)

    pipeline.bus.subscribe("collect", sink)

    count = 0
    async for item in provider.run(session):
        count += await pipeline.process(item)

    assert count == 5
    assert len(seen) == 5
    # original timestamps preserved; order preserved; origin flagged
    seqs = [e.seq for e in seen]
    assert seqs == sorted(seqs)
    assert all(e.origin == "replay" for e in seen)
    temps = [e.payload["model"]["air_temp_c"] for e in seen]
    assert temps == [20.0, 21.0, 22.0, 23.0, 24.0]


async def test_replay_through_full_pipeline_dedupes_against_live(recording: Path) -> None:
    """A frame recorded live, when replayed twice into the same pipeline state,
    must be recognized as duplicate (dedupe_key survives the round-trip)."""
    provider = ReplayProvider(recording)
    provider.set_speed(0)
    session = await provider.resolve_session(str(recording))
    pipeline = IngestPipeline(session_id=session.session_id)

    collected: list[RawItem] = []
    async for item in provider.run(session):
        collected.append(item)
    for item in collected:
        await pipeline.process(item)
        await pipeline.process(item)  # immediate re-delivery simulation
    assert pipeline.quality.duplicate_events == 5


async def test_discover_lists_recordings(recording: Path) -> None:
    provider = ReplayProvider(recording.parent)  # recordings root
    sessions = await provider.discover_sessions()
    names = [s.provider_session_key for s in sessions]
    assert any("test-recording" in n for n in names)


async def test_missing_recording_fails_cleanly(tmp_path: Path) -> None:
    provider = ReplayProvider(tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        session_dir = tmp_path / "nope"
        session = await provider.resolve_session(str(session_dir))
        async for _ in provider.run(session):
            pass
