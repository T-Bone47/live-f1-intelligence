"""ReplayProvider - emits recorded canonical envelopes through the same
pipeline interfaces as a live provider.

Recording format (written by app.ingest.recorder):
  recordings/<name>/meta.json      session metadata + recording info
  recordings/<name>/frames.jsonl.zst   one JSON object per line:
      {"seq": int, "envelope": {..canonical envelope..}}

Replay preserves original source timestamps. Playback speed scales the
inter-frame wall delays; speed<=0 means "as fast as possible".
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from app.core.enums import ProvenanceClass, ProviderName
from app.core.events import Envelope
from app.core.models import SessionInfo, Team, Driver, Lap  # noqa: F401 (typing refs)
from app.providers.base import Capabilities, Channel, RawItem

log = logging.getLogger(__name__)


class ReplayProvider:
    name = "replay"

    def __init__(self, recording_dir: Path) -> None:
        self._dir = Path(recording_dir)
        self.meta: dict = {}
        self._frames_path = self._dir / "frames.jsonl.zst"
        self._speed: float = 1.0

    def capabilities(self) -> Capabilities:
        # capabilities mirror exactly what the recording contains - no more
        return Capabilities(
            session_discovery=True,
            historical=True,
            laps=self._has("lap.completed"),
            sectors=self._has("sector.recorded"),
            mini_segments=self._has("sector.recorded"),
            telemetry_car=self._has("telemetry.car_sample"),
            telemetry_location=self._has("telemetry.location_sample"),
            stints=self._has("tyre.stint_recorded"),
            pits=self._has("pit.recorded"),
            weather=self._has("weather.updated"),
            race_control=self._has("rcm.message"),
            positions=self._has("position.changed"),
            timing_intervals=self._has("timing.interval_updated"),
            lap_corrections=self._has("lap.deleted"),
            results=self._has("result."),
            standings=self._has("standings.entry"),
            notes=tuple(self.meta.get("capabilities_notes", ("recorded replay",))),
        )

    def _has(self, event_type_prefix: str) -> bool:
        types = self.meta.get("event_types", [])
        return any(t.startswith(event_type_prefix) for t in types)

    async def discover_sessions(self, year: int | None = None) -> list[SessionInfo]:
        """Each local recording appears as one replayable session."""
        sessions: list[SessionInfo] = []
        base = self._dir.parent if self._dir.name.startswith("frames") else self._dir
        for child in sorted(base.glob("*/meta.json")):
            try:
                meta = json.loads(child.read_text(encoding="utf-8-sig"))
                raw = dict(meta.get("session", {}))
                now_iso = datetime.now(tz=timezone.utc).isoformat()
                prov = raw.get("provenance") or {
                    "provider": "openf1",
                    "provenance_class": "B",
                    "source_timestamp": raw.get("date_start"),
                    "ingestion_timestamp": now_iso,
                }
                info = {
                    **raw,
                    "provider": ProviderName.REPLAY.value,
                    "session_id": f"replay:{child.parent.name}",
                    "provider_session_key": raw.get("provider_session_key")
                    or child.parent.name,
                    "status": raw.get("status") or "FINISHED",
                    "is_cancelled": bool(raw.get("is_cancelled", False)),
                    "provenance": prov,
                }
                sessions.append(SessionInfo.model_validate(info))
            except Exception as exc:  # noqa: BLE001
                log.warning("unreadable recording meta at %s: %s", child, exc)
        return sessions

    async def resolve_session(self, session_ref: str) -> SessionInfo:
        """Load a recording's meta into a SessionInfo, tolerating partial metas."""
        target = session_ref.removeprefix("replay:")
        path = Path(target)
        if path.is_dir():
            meta_file = path / "meta.json"
            self._dir = path
        else:
            # treat as recording name under the recordings root
            base = self._dir.parent if self._dir.name.startswith("frames") else self._dir.parent
            candidate = Path(target)
            meta_file = (
                candidate / "meta.json"
                if (candidate / "meta.json").exists()
                else base / target / "meta.json"
            )
            self._dir = meta_file.parent
        self._frames_path = self._dir / "frames.jsonl.zst"
        self.meta = json.loads(meta_file.read_text(encoding="utf-8-sig"))
        raw = dict(self.meta.get("session", {}))
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        prov = raw.get("provenance") or {
            "provider": raw.get("provider", "openf1"),
            "provenance_class": "B",
            "source_timestamp": raw.get("date_start"),
            "ingestion_timestamp": now_iso,
        }
        info = {
            **raw,
            "provider": ProviderName.REPLAY.value,
            "session_id": f"replay:{self._dir.name}",
            "provider_session_key": raw.get("provider_session_key") or self._dir.name,
            "status": raw.get("status") or "FINISHED",
            "is_cancelled": bool(raw.get("is_cancelled", False)),
            "provenance": prov,
        }
        return SessionInfo.model_validate(info)

    def set_speed(self, speed: float) -> None:
        self._speed = speed

    async def run(self, session: SessionInfo) -> AsyncIterator[RawItem]:
        """Yield recorded envelopes re-shaped as RawItems.

        The pipeline recognizes these as already-canonical (payload key
        "__envelope") and routes them straight onto the bus without vendor
        normalization - proving live/replay share one interface.
        """
        from zstandard import ZstdDecompressor  # local import keeps import cost lazy

        if not self._frames_path.exists():
            raise FileNotFoundError(f"recording missing frames: {self._frames_path}")
        prev_wall: float | None = None
        dctx = ZstdDecompressor()
        # Local-file streaming reads are cheap and bounded; sync I/O here keeps
        # ordering simple while asyncio.sleep provides the pacing.
        with open(self._frames_path, "rb") as fh:
            reader = dctx.stream_reader(fh)
            buf = b""
            while True:
                chunk = reader.read(1 << 20)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for env in self._iter_envelopes(lines):
                    yield await self._paced(env, prev_wall)
                    prev_wall = env.ingestion_timestamp.timestamp()
            if buf.strip():
                for env in self._iter_envelopes([buf]):
                    yield await self._paced(env, prev_wall)
                    prev_wall = env.ingestion_timestamp.timestamp()

    def _iter_envelopes(self, raw_lines: list[bytes]) -> list[Envelope]:
        out: list[Envelope] = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line.decode("utf-8"))
            out.append(Envelope.model_validate(record["envelope"]))
        return out

    async def _paced(self, env: Envelope, prev_wall: float | None) -> RawItem:
        wall = env.ingestion_timestamp.timestamp()
        if prev_wall is not None and self._speed > 0:
            delay = (wall - prev_wall) / max(self._speed, 1e-9)
            if delay > 5.0:  # collapse long real-world pauses
                delay = 0.05
            elif delay < 0:  # defensive against unordered frames
                delay = 0.0
            if delay > 0:
                await asyncio.sleep(min(delay, 2.0))
        return RawItem(
            channel=Channel.SESSION_META,  # channel is informational here
            payload={"__envelope": env.model_dump(mode="json")},
            source_timestamp=env.source_timestamp,
            provenance_class=ProvenanceClass(env.provenance_class),
        )
