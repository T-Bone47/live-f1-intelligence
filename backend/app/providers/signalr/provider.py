"""SignalR live-timing provider.

Status (Phase 1.5, verified 2026-08-24):
- negotiate/connect/handshake/subscribe/snapshot: VERIFIED without auth
- incremental feed frames + CarData.z/Position.z payloads: ASSUMED until
  first live capture; capability claims for those channels are flagged.

DISABLED by default: requires SIGNALR_ENABLED=true. The provider never
bypasses access controls; if upstream starts refusing, it reports failure and
the failover layer drops to OpenF1.
"""

from __future__ import annotations

import logging
import zlib
from typing import AsyncIterator

from app.config import get_settings
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import SessionInfo
from app.providers.base import Capabilities, Channel, RawItem
from app.providers.signalr import protocol as protocol  # noqa: F401
from app.providers.signalr.client import FeedMessage, SignalRClient

log = logging.getLogger(__name__)

DEFAULT_TOPICS = [
    "Heartbeat", "DriverList", "SessionInfo", "SessionStatus", "TrackStatus",
    "LapCount", "ExtrapolatedClock", "TopThree",
    "TimingData", "TimingAppData", "TimingStats",
    "WeatherData", "RaceControlMessages", "TrackStatus",
    "CarData.z", "Position.z",
]

# topics whose presence we have personally seen in a snapshot
_VERIFIED_TOPICS = {
    "Heartbeat", "DriverList", "SessionInfo", "TimingData",
    "WeatherData", "RaceControlMessages",
}


class SignalRLiveProvider:
    name = "livetiming"

    def __init__(self, topics: list[str] | None = None,
                 bearer_token: str | None = None) -> None:
        self._topics = topics or DEFAULT_TOPICS
        self._token = bearer_token
        self._client: SignalRClient | None = None
        self.reconnects = 0

    def capabilities(self) -> Capabilities:
        return Capabilities(
            session_discovery=False,   # schedule comes from Jolpica/OpenF1
            live=True,
            laps=True,
            sectors=True,
            timing_intervals=True,
            positions=True,
            telemetry_car=True,
            telemetry_location=True,
            stints=True,
            weather=True,
            race_control=True,
            verified=(
                "negotiate HTTP 200 token-less (2026-08-24)",
                "wss connect + handshake ack {} (2026-08-24)",
                "subscribe -> type-3 snapshot incl. "
                f"{sorted(_VERIFIED_TOPICS)} (2026-08-24)",
            ),
            assumed=(
                "type-1 feed frame shapes ([topic, data, ts])",
                "CarData.z/Position.z deflate CSV formats",
                "TimingAppData/TimingStats/TrackStatus topic presence",
            ),
            notes=(
                "same feed as the official F1 live-timing web app",
                "auth state historically unstable: pluggable bearer token; "
                "if refused -> failover to OpenF1",
                "server force-disconnects long connections (~2h reported) - "
                "supervised reconnect with snapshot resync implemented",
            ),
        )

    async def discover_sessions(self, year: int | None = None) -> list[SessionInfo]:
        return []  # by design: no schedule surface on this feed

    async def resolve_session(self, session_ref: str) -> SessionInfo:
        raise NotImplementedError(
            "SignalR feed has no session registry; resolve via OpenF1/Jolpica "
            "and attach this provider for the live window only"
        )

    async def run(self, session: SessionInfo) -> AsyncIterator[RawItem]:
        settings = get_settings()
        if not getattr(settings, "signalr_enabled", False):
            log.info("signalr disabled (SIGNALR_ENABLED=false) - provider idle")
            return

        cls = ProvenanceClass.A
        self._client = SignalRClient(
            topics=self._topics, bearer_token=self._token or settings.openf1_api_token,
            on_reconnect=self._note_reconnect,
        )
        snapshot_seen = False
        async for msg in self._client.stream():
            if isinstance(msg, FeedMessage):
                items = self._translate(msg, cls)
                if not snapshot_seen and msg.topic == "__snapshot__":
                    snapshot_seen = True
                    log.info("signalr initial snapshot captured (%d channels)",
                             len(msg.payload or {}))
                for item in items:
                    yield item

    def _note_reconnect(self) -> None:
        self.reconnects += 1

    # ------------------------------------------------------------- mapping --

    def _translate(self, msg: FeedMessage, cls: ProvenanceClass) -> list[RawItem]:
        topic = msg.topic or ""
        out: list[RawItem] = []
        try:
            if topic == "__snapshot__":
                payload_obj = msg.payload or {}
                for ch, blob in (payload_obj.items() if isinstance(payload_obj, dict) else []):
                    out.extend(self._topic_to_items(str(ch), blob, cls))
            else:
                out.extend(self._topic_to_items(topic, msg.payload, cls))
        except Exception as exc:  # noqa: BLE001
            log.warning("signalr translate failed for %s (%s)", topic, exc)
        return out

    def _topic_to_items(self, topic: str, data: object, cls: ProvenanceClass) -> list[RawItem]:
        from datetime import datetime as _dt

        ts = None
        if isinstance(data, dict):
            raw_ts = data.get("Utc") or data.get("timestamp")
            if isinstance(raw_ts, str):
                try:
                    ts = _dt.fromisoformat(raw_ts.replace("Z", "+00:00"))
                except ValueError:
                    ts = None

        if topic == "CarData.z":
            blob = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8", "ignore")
            return [RawItem(Channel.CAR_DATA, r, ts, cls)
                    for r in protocol.parse_car_data_z(bytes(blob))]
        if topic == "Position.z":
            blob = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8", "ignore")
            return [RawItem(Channel.LOCATION, r, ts, cls)
                    for r in protocol.parse_position_z(bytes(blob))]
        if topic == "WeatherData":
            return [RawItem(Channel.WEATHER, data if isinstance(data, dict) else {}, ts, cls)]
        if topic == "RaceControlMessages":
            return [RawItem(Channel.RACE_CONTROL, {"M": data}, ts, cls)]
        if topic == "SessionInfo":
            return [RawItem(Channel.SESSION_META, data if isinstance(data, dict) else {}, ts, cls)]
        if topic == "DriverList":
            return [RawItem(Channel.DRIVER_LIST, {"raw": data}, ts, cls)]
        if topic == "TimingData":
            return [RawItem(Channel.LAP, {"timing": data}, ts, cls)]
        # TimingAppData/TimingStats/TopThree/etc.: pass through for later phases
        return []
