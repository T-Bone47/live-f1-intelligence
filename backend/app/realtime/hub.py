"""SessionHub (Phase 3): one upstream, many clients.

    Provider -> IngestPipeline -> AnalysisEngine -> SnapshotDiffer
                                            │ 250 ms publish loop
                                            ▼
                              per-client bounded queues ─▶ WebSocket

Backpressure policy (documented in TELEMETRY_STREAMING/SCALING):
- Publisher NEVER blocks on a slow client.
- Per-client queue (default 400). On overflow: drop queued DELTA/TELEMETRY
  frames first (counted); SNAPSHOT/EVENTS frames are never dropped - if the
  queue still overflows with only critical frames the client is EVICTED.
- Critical events (severity >= IMPORTANT or types in CRITICAL_EVENT_TYPES)
  bypass batching and are enqueued immediately as their own frame.

Redis: optional transport for multi-process gateway scale-out. When
REDIS_URL is unset the hub runs fully in-process (development mode).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.analysis import AnalysisEngine
from app.core.events import Envelope, EventBus
from app.ingest.pipeline import IngestPipeline
from app.realtime.differ import SnapshotDiffer
from app.realtime.metrics import RealtimeMetrics
from app.realtime.models import (
    FrameKind,
    SCHEMA_VERSION,
    utcnow_iso,
)
from app.realtime.sequencer import SequenceHistory, SequencedFrame
from app.realtime.telemetry import TelemetryCoalescer

log = logging.getLogger(__name__)

BATCH_INTERVAL_S = 0.25
CRITICAL_SEVERITIES = {"IMPORTANT", "CRITICAL"}
CRITICAL_EVENT_TYPES = {
    "SAFETY_CAR", "VSC", "RED_FLAG", "SESSION_STATE_CHANGE",
    "OVERTAKE", "FASTEST_LAP_CHANGE",
}
CLIENT_QUEUE_SIZE = 400


@dataclass
class ClientConnection:
    client_id: str
    queue: asyncio.Queue[SequencedFrame | str]
    drivers: set[int] | None = None            # None = all
    telemetry_drivers: set[int] = field(default_factory=set)
    wants_events: bool = True
    wants_deltas: bool = True
    dropped_frames: int = 0


class SessionHub:
    """Authoritative runtime for one session: ingest+analysis+realtime fanout."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.pipeline = IngestPipeline(session_id=session_id)
        self.engine = AnalysisEngine(session_id=session_id)
        self.differ = SnapshotDiffer()
        self.history = SequenceHistory(capacity=2000)
        self.metrics = RealtimeMetrics()
        self.clients: dict[str, ClientConnection] = {}
        self._publish_task: asyncio.Task | None = None
        self._last_publish = time.monotonic()
        self._pending_events: list[dict] = []
        self._running = False
        # wire analysis into the same bus so live and replay share one path;
        # intelligence events notify via engine listener (works for
        # deferred/flush-time emissions too)
        async def _on_env(env: Envelope) -> None:
            t0 = time.perf_counter()
            self.engine.process_envelope(env)
            self.metrics.events_seen += 1
            self.metrics.observe_analysis((time.perf_counter() - t0) * 1000)

        def _on_intelligence(ev) -> None:  # noqa: ANN001 IntelligenceEvent
            if ev.event_type in CRITICAL_EVENT_TYPES or \
                    ev.severity.value in CRITICAL_SEVERITIES:
                self._queue_critical_event(ev.as_dict())
            else:
                self._pending_events.append(ev.as_dict())

        self.pipeline.bus.subscribe("analysis", _on_env)
        self.engine.sig.listeners.append(_on_intelligence)

        # live telemetry channel: latest-wins coalescing per driver
        self.telemetry = TelemetryCoalescer()

        async def _on_telemetry(env: Envelope) -> None:
            info = env.payload.get("model", {})
            if info.get("type") != "TelemetryCarSample":
                return
            sample = {
                "ts": info.get("ts"),
                "speed_kph": info.get("speed_kph"),
                "rpm": info.get("rpm"),
                "gear": info.get("gear"),
                "throttle_pct": info.get("throttle_pct"),
                "brake_pct": info.get("brake_pct"),
                "drs": info.get("drs"),  # nullable upstream - preserved
            }
            self.telemetry.offer(int(info["driver_number"]), sample)

        self.pipeline.bus.subscribe("telemetry", _on_telemetry)

    def attach_ai(self, runtime) -> None:  # noqa: ANN001 AIRuntime
        """Phase 6: attach an AIRuntime. Events route to the AI queue via a
        dedicated listener; AI responses broadcast as kind=ai frames."""

        def ai_trigger(ev) -> None:  # noqa: ANN001
            try:
                runtime.trigger_from_event(ev)
            except Exception:  # noqa: BLE001
                log.exception("ai trigger failed")

        self.engine.sig.listeners.append(ai_trigger)
        runtime.attach(self.engine,
                       broadcast=self.broadcast_ai,
                       get_current_seq=lambda: self.history.current)

    # ------------------------------------------------------------ clients ---

    async def subscribe(self, client_id: str, *, drivers: set[int] | None = None,
                        telemetry_drivers: set[int] | None = None,
                        wants_events: bool = True) -> ClientConnection:
        conn = ClientConnection(
            client_id=client_id,
            queue=asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE),
            drivers=drivers,
            telemetry_drivers=telemetry_drivers or set(),
            wants_events=wants_events,
        )
        self.clients[client_id] = conn
        self.metrics.clients_connected = len(self.clients)
        # full snapshot first, sequenced ahead of the loop
        snap = self.engine.snapshot_dict()
        final: dict[str, Any] = {"kind": "snapshot", "data": snap,
                                 "ts": utcnow_iso(), "schema": SCHEMA_VERSION}
        seq_frame = self.history.next("snapshot", final)
        final["seq"] = seq_frame.seq
        conn.queue.put_nowait(SequencedFrame(seq_frame.seq, "snapshot", final))
        return conn

    def broadcast_ai(self, payload: dict) -> None:
        """Sequenced kind=ai frame to all clients wanting events."""
        final = {"kind": "ai", "ts": utcnow_iso(), "schema": SCHEMA_VERSION,
                 **payload}
        seq_frame = self.history.next("ai",
                                      {k: v for k, v in final.items() if k != "seq"})
        final["seq"] = seq_frame.seq
        frame = SequencedFrame(seq_frame.seq, "ai", final)
        for conn in list(self.clients.values()):
            if conn.wants_events:
                self._put(conn, frame)

    def unsubscribe(self, client_id: str) -> None:
        self.clients.pop(client_id, None)
        self.metrics.clients_connected = len(self.clients)

    # ------------------------------------------------------------- intake ---

    async def feed(self, item) -> int:   # noqa: ANN001 RawItem
        t0 = time.perf_counter()
        n = await self.pipeline.process(item)
        if n == 0:
            self.metrics.observe_analysis((time.perf_counter() - t0) * 1000 + 1e-6)
        # cooperative yield: max-speed replay is CPU-bound with no natural
        # suspension points; without this the publish loop and WS clients
        # starve the event loop entirely (verified Phase 7).
        await asyncio.sleep(0)
        return n

    # ------------------------------------------------- critical fast path ----

    def _queue_critical_event(self, event_dict: dict) -> None:
        self._pending_events.append(event_dict)
        # immediate flush of pending events as a critical frame
        final = {"kind": "events", "events": list(self._pending_events),
                 "critical": True, "ts": utcnow_iso(),
                 "schema": SCHEMA_VERSION}
        self._pending_events.clear()
        seq_frame = self.history.next("events",
                                      {k: v for k, v in final.items() if k != "seq"})
        final["seq"] = seq_frame.seq
        frame = SequencedFrame(seq_frame.seq, "events", final)
        for conn in list(self.clients.values()):
            if not conn.wants_events:
                continue
            self._put(conn, frame)

    # ---------------------------------------------------------- publishing --

    async def run(self) -> None:
        """250 ms snapshot-diff publish loop."""
        self._running = True
        while self._running:
            await asyncio.sleep(BATCH_INTERVAL_S)
            try:
                await self.publish_once()
            except Exception:  # noqa: BLE001
                log.exception("publish cycle failed")
                self.metrics.last_error = "publish cycle error"

    async def publish_once(self) -> SequencedFrame | None:
        # ensure context-deferred events are folded before projecting
        # (no-op when already primed)
        self.engine.flush_deferred()
        t0 = time.perf_counter()
        snap = self.engine.snapshot_dict()
        self.metrics.observe_snapshot((time.perf_counter() - t0) * 1000)

        is_full, changes, removed = self.differ.first_diff(snap)
        t1 = time.perf_counter()
        self.metrics.observe_diff((time.perf_counter() - t1) * 1000,
                                  len(json.dumps(changes, default=str)))

        if is_full:
            frame_payload = {"data": snap}
            kind = FrameKind.SNAPSHOT.value
        else:
            if not changes and not removed and not self._pending_events:
                return None
            frame_payload = {"changes": changes, "removed": removed}
            kind = FrameKind.DELTA.value

        seq_frame = self.history.next(kind, frame_payload)
        payload: dict[str, Any] = dict(frame_payload)
        payload.update({"kind": kind, "seq": seq_frame.seq,
                        "ts": utcnow_iso(), "schema": SCHEMA_VERSION})
        # piggyback non-critical batched events onto the delta frame
        if self._pending_events:
            payload["events"] = list(self._pending_events)
            self._pending_events.clear()

        size = len(json.dumps(payload, default=str))
        self.metrics.delta_bytes.append(size)
        frame = SequencedFrame(seq_frame.seq, kind, payload)
        for conn in list(self.clients.values()):
            if not conn.wants_deltas and kind == FrameKind.DELTA.value:
                continue
            self._put(conn, frame)

        # telemetry frames: only to clients subscribed to those drivers
        now = time.monotonic()
        if self.telemetry and self.telemetry.due(now, getattr(self, "_t_last_tel", 0.0)):
            self._t_last_tel = now
            drained = self.telemetry.drain()
            for conn in list(self.clients.values()):
                if not conn.telemetry_drivers:
                    continue
                for dn in list(conn.telemetry_drivers):
                    if dn in drained:
                        final = {"kind": "telemetry", "driver": dn,
                                 "samples": drained[dn],
                                 "ts": utcnow_iso(), "schema": SCHEMA_VERSION}
                        seq_frame = self.history.next("telemetry",
                                                      {k: v for k, v in final.items() if k != "seq"})
                        final["seq"] = seq_frame.seq
                        self._put(conn, SequencedFrame(seq_frame.seq, "telemetry", final))
        return frame

    # ------------------------------------------------------- backpressure ---

    def _put(self, conn: ClientConnection, frame: SequencedFrame) -> None:
        """Non-blocking delivery with documented backpressure policy.

        - DELTA/TELEMETRY onto full queue  -> frame dropped for this client
          (counted); publisher never blocks.
        - SNAPSHOT/EVENTS onto full queue  -> client EVICTED. Critical frames
          are never silently lost; a client too slow to receive them is
          disconnected instead (client reconnects and resumes by sequence).
        """
        q = conn.queue
        critical = frame.kind in (FrameKind.SNAPSHOT.value, "events")
        if not q.full():
            q.put_nowait(frame)
            return
        if critical:
            self._evict(conn, reason=f"{frame.kind} overflow")
            return
        conn.dropped_frames += 1
        self.metrics.deltas_dropped_for_slow_clients += 1

    def _evict(self, conn: ClientConnection, reason: str) -> None:
        log.warning("evicting slow client %s (%s)", conn.client_id, reason)
        # sentinel lets the client handler exit cleanly on next receive
        try:
            conn.queue.put_nowait("__evicted__")
        except asyncio.QueueFull:
            pass
        self.unsubscribe(conn.client_id)
        self.metrics.slow_client_evictions += 1

    async def next_for(self, conn: ClientConnection):  # noqa: ANN201
        item = await conn.queue.get()
        if isinstance(item, str) and item == "__evicted__":
            raise ConnectionError("client evicted (slow consumer)")
        return item

    # ---------------------------------------------------------------- stop --

    def stop(self) -> None:
        self._running = False
