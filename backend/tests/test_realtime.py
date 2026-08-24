"""Phase-3 realtime tests: diffs, sequences, resume, batching, backpressure,
coalescing, fanout, REST/WS contracts."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.analysis import AnalysisEngine
from app.api import HubRegistry, RateLimiter, create_app
from app.core.events import Envelope
from app.realtime.differ import SnapshotDiffer, compute_diff
from app.realtime.hub import SessionHub
from app.realtime.sequencer import SequenceHistory
from app.realtime.telemetry import TelemetryCoalescer


def make_env(mtype: str, data: dict) -> Envelope:
    from datetime import datetime, timezone

    return Envelope(
        event_type="x", session_id="s", source="test",
        ingestion_timestamp=datetime.now(timezone.utc),
        provenance_class="A",
        payload={"model": {"type": mtype, **data}},
    )


def lap_env(num, dur):
    return make_env("Lap", {
        "session_id": "s", "driver_number": 1, "lap_number": num,
        "started_at": "2026-08-23T13:00:00+00:00", "duration_s": dur,
        "sector1_s": None, "sector2_s": None, "sector3_s": None,
        "is_pit_out_lap": False, "deleted": False,
        "speed_traps": {"i1_kph": None, "i2_kph": None, "st_kph": None},
        "provenance": {"provider": "openf1", "provenance_class": "A"},
    })


class TestSnapshotDiff:
    def test_flat_diff_detects_changes_and_removals(self):
        old = {"a": 1, "b": {"x": 2, "y": 3}, "gone": [1, 2]}
        new = {"a": 1, "b": {"x": 9, "y": 3}}
        changes, removed = compute_diff(old, new)
        assert changes == {"b.x": 9}
        assert removed == ["gone"]

    def test_lists_are_atomic(self):
        changes, _ = compute_diff({"rows": [1, 2]}, {"rows": [1, 2, 3]})
        assert changes == {"rows": [1, 2, 3]}

    def test_differ_first_returns_full(self):
        d = SnapshotDiffer()
        full, changes, removed = d.first_diff({"a": 1})
        assert full is True and changes == {"a": 1} and removed == []

    def test_second_returns_delta(self):
        d = SnapshotDiffer()
        d.first_diff({"a": 1, "b": 2})
        full, changes, removed = d.first_diff({"a": 2})
        assert full is False and changes == {"a": 2} and removed == ["b"]

    def test_no_change_empty_delta(self):
        d = SnapshotDiffer()
        d.first_diff({"a": 1})
        _, changes, removed = d.first_diff({"a": 1})
        assert changes == {} and removed == []


class TestSequenceResume:
    def test_monotonic_sequences(self):
        h = SequenceHistory()
        f1 = h.next("delta", {})
        f2 = h.next("delta", {})
        assert f2.seq == f1.seq + 1

    def test_since_returns_missing_range(self):
        h = SequenceHistory()
        for i in range(10):
            h.next("delta", {"i": i})
        missed = h.since(7)
        assert [f.seq for f in missed] == [8, 9, 10]

    def test_history_capacity_bounds(self):
        h = SequenceHistory(capacity=5)
        for i in range(20):
            h.next("delta", {})
        assert h.oldest_available == 16
        assert len(h.since(0)) == 5   # only retained window


class TestTelemetryCoalescer:
    def test_latest_wins_and_counts_stale(self):
        c = TelemetryCoalescer()
        assert c.offer(1, {"speed": 100}) is False
        assert c.offer(1, {"speed": 150}) is True   # stale intermediate dropped
        out = c.drain()
        assert out[1][0]["speed"] == 150
        assert c.dropped_stale == 1

    def test_drain_clears_state(self):
        c = TelemetryCoalescer()
        c.offer(2, {"speed": 90})
        c.drain()
        assert len(c) == 0

    def test_flush_interval_due_logic(self):
        c = TelemetryCoalescer(flush_interval_s=0.25)
        t0 = 100.0
        assert c.due(t0 + 0.2, t0) is False
        assert c.due(t0 + 0.3, t0) is True


class TestHubFanoutAndBackpressure:
    async def test_subscribe_receives_full_snapshot_first(self):
        hub = SessionHub("s")
        conn = await hub.subscribe("c1")
        frame = await hub.next_for(conn)
        assert frame.kind == "snapshot"
        assert "data" in frame.payload and frame.seq >= 1

    async def test_multiple_clients_each_get_snapshot(self):
        hub = SessionHub("s")
        conns = [await hub.subscribe(f"c{i}") for i in range(3)]
        for c in conns:
            f = await hub.next_for(c)
            assert f.kind == "snapshot"
        assert hub.metrics.clients_connected == 3

    async def test_publish_once_produces_delta_after_full(self):
        hub = SessionHub("s")
        conn = await hub.subscribe("c")
        await hub.next_for(conn)
        # feed laps directly through analysis to change state
        for n, dur in [(1, 90.0), (2, 89.5)]:
            hub.engine.process_envelope(lap_env(n, dur))
        await hub.publish_once()
        f = await asyncio.wait_for(hub.next_for(conn), timeout=2)
        # first frame may be a critical PB/event frame or the delta itself
        assert f.kind in ("delta", "snapshot", "events")

    async def test_critical_event_bypasses_batching(self):
        hub = SessionHub("s")
        conn = await hub.subscribe("c")
        await hub.next_for(conn)  # drain snapshot
        from datetime import datetime, timezone

        ev_dict = {"event_type": "RED_FLAG", "severity": "CRITICAL",
                   "timestamp": datetime.now(timezone.utc).isoformat()}
        hub._queue_critical_event(ev_dict)
        f = await asyncio.wait_for(hub.next_for(conn), timeout=1)
        assert f.kind == "events"
        assert f.payload["critical"] is True
        assert f.payload["events"][0]["event_type"] == "RED_FLAG"

    async def test_slow_client_drops_delta_not_publisher(self):
        hub = SessionHub("s")
        conn = await hub.subscribe("c")
        await hub.next_for(conn)
        # fill the queue with deltas beyond capacity
        for i in range(500):
            hub.history.next("delta", {"n": i})
            hub._put(conn, __import__(
                "app.realtime.sequencer", fromlist=["SequencedFrame"]
            ).SequencedFrame(seq=i, kind="delta", payload={"n": i}))
        assert conn.dropped_frames > 0           # non-critical dropped
        assert hub.metrics.deltas_dropped_for_slow_clients > 0

    async def test_slow_client_evicted_on_critical_overflow(self):
        hub = SessionHub("s")
        conn = await hub.subscribe("c")
        while not conn.queue.full():
            conn.queue.put_nowait(__import__(
                "app.realtime.sequencer", fromlist=["SequencedFrame"]
            ).SequencedFrame(seq=999, kind="delta", payload={}))
        from datetime import datetime, timezone

        hub._queue_critical_event({"event_type": "OVERTAKE",
                                   "timestamp": datetime.now(timezone.utc).isoformat()})
        assert conn.client_id not in hub.clients          # evicted
        assert hub.metrics.slow_client_evictions >= 1

    async def test_analysis_events_flow_via_pipeline_bus(self):
        from app.providers.base import Channel, RawItem

        hub = SessionHub("s")
        conn = await hub.subscribe("c")
        await hub.next_for(conn)  # drain snapshot
        for num, dur in ((1, 85.0), (2, 84.0)):
            raw = RawItem(
                Channel.LAP,
                {"session_key": "s", "driver_number": 1, "lap_number": num,
                 "date_start": "2026-08-23T13:00:00+00:00",
                 "lap_duration": dur, "duration_sector_1": 30.0,
                 "duration_sector_2": 29.0, "duration_sector_3": None,
                 "is_pit_out_lap": False,
                 "segments_sector_1": None, "segments_sector_2": None,
                 "segments_sector_3": None,
                 "i1_speed": None, "i2_speed": None, "st_speed": 240},
                None, "A",
            )
            await hub.pipeline.process(raw)
        # laps may be context-deferred; flush before draining (hub does this
        # in its publish loop too)
        hub.engine.flush_deferred()
        got_types = set()
        try:
            while True:
                f = await asyncio.wait_for(hub.next_for(conn), timeout=0.6)
                if f.kind == "events":
                    got_types |= {e["event_type"] for e in f.payload.get("events", [])}
                if "FASTEST_LAP_CHANGE" in got_types:
                    break
        except (asyncio.TimeoutError, StopAsyncIteration):
            pass
        assert "FASTEST_LAP_CHANGE" in got_types


class TestRestApi:
    def _app_with_hub(self):
        registry = HubRegistry()
        hub = SessionHub("openf1:test")
        registry.register(hub)
        hub.engine.process_envelope(lap_env(1, 85.0))
        return create_app(registry), hub

    def test_rest_snapshot_shape(self):
        app, _hub = self._app_with_hub()
        client = TestClient(app)
        r = client.get("/api/v1/sessions/openf1:test/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["schema"] == "f1intel-snapshot-1"
        assert "leaderboard" in body and "phase" in body

    def test_rest_unknown_session_404(self):
        app, _ = self._app_with_hub()
        client = TestClient(app)
        assert client.get("/api/v1/sessions/nope/snapshot").status_code == 404

    def test_rest_drivers_leaderboard_events(self):
        app, hub = self._app_with_hub()
        client = TestClient(app)
        assert client.get("/api/v1/sessions/openf1:test/drivers").status_code == 200
        lb = client.get("/api/v1/sessions/openf1:test/leaderboard").json()
        assert "leaderboard" in lb
        ev = client.get("/api/v1/sessions/openf1:test/events?limit=50").json()
        assert ev["count"] <= 50

    def test_rest_driver_subresources(self):
        app, hub = self._app_with_hub()
        hub.engine.process_envelope(make_env("SectorTime", {
            "session_id": "openf1:test", "driver_number": 1, "lap_number": 1,
            "sector_index": 1, "time_s": 26.5, "segment_codes": None,
            "provenance": {"provider": "openf1", "provenance_class": "A"},
        }))
        hub.engine.flush_deferred()   # read-only views fold pending context
        client = TestClient(app)
        s = client.get("/api/v1/sessions/openf1:test/sectors/1")
        assert s.status_code == 200
        assert s.json()["personal_best"]["S1"] == 26.5
        p = client.get("/api/v1/sessions/openf1:test/pace/1")
        assert p.status_code == 200 and "rolling_5_s" in p.json()
        t = client.get("/api/v1/sessions/openf1:test/tyres/1")
        assert t.status_code == 200  # available may be False - honest

    def test_rate_limiter_blocks_flood(self):
        rl = RateLimiter(per_minute=3)
        assert rl.check("ip") is True
        assert rl.check("ip") is True
        assert rl.check("ip") is True
        assert rl.check("ip") is False
        assert rl.check("other-ip") is True

    def test_invalid_session_id_rejected(self):
        from fastapi import HTTPException

        from app.api import validate_session_id

        with pytest.raises(HTTPException):
            validate_session_id("../evil")


class TestReplayAsRealtime:
    async def test_replay_provider_through_hub_produces_frames(self):
        """Provider-independent contract: replay feeds the same hub."""
        from pathlib import Path

        from app.providers.replay import ReplayProvider

        fixture_dir = Path(__file__).parent / "fixtures"
        recording = fixture_dir / "mini-recording"
        if not recording.exists():
            pytest.skip("mini recording fixture not built")
        provider = ReplayProvider(recording)
        provider.set_speed(0)
        session = await provider.resolve_session(str(recording))
        hub = SessionHub(session_id=f"replay:{recording.name}")
        count = 0
        async for item in provider.run(session):
            count += await hub.feed(item)
        hub.engine.flush_deferred()
        await hub.publish_once()
        assert count > 0
        snap = hub.engine.snapshot_dict()
        assert snap["session_id"].startswith("replay:")


class TestFailureModes:
    def test_redis_absence_is_graceful_by_design(self):
        """No Redis configured -> hub works fully in-process."""
        hub = SessionHub("s")
        assert hub.metrics.redis_enabled is False
        assert hub.metrics.redis_status == "DISABLED"

    def test_metrics_shape(self):
        hub = SessionHub("s")
        m = hub.metrics.as_dict()
        for key in ("provider", "analysis_latency_ms", "snapshot_latency_ms",
                    "diff_latency_ms", "websocket", "redis"):
            assert key in m
