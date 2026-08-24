"""Wire-format models for the realtime gateway (Phase 3).

Protocol: f1intel-realtime-v1

Every outbound frame:
    { kind, session_id, seq, ts, schema, ...payload }

kinds: snapshot | delta | events | telemetry | control | pong
Sequence numbers are per-session monotonic integers shared across all kinds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

SCHEMA_VERSION = "f1intel-snapshot-1"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FrameKind(str, Enum):
    SNAPSHOT = "snapshot"
    DELTA = "delta"
    EVENTS = "events"
    TELEMETRY = "telemetry"
    CONTROL = "control"
    PONG = "pong"


@dataclass(frozen=True)
class SnapshotFrame:
    session_id: str
    seq: int
    data: dict[str, Any]
    ts: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": FrameKind.SNAPSHOT.value,
            "session_id": self.session_id,
            "seq": self.seq,
            "ts": self.ts,
            "schema": SCHEMA_VERSION,
            "data": self.data,
        }


@dataclass(frozen=True)
class DeltaFrame:
    session_id: str
    seq: int
    changes: dict[str, Any]
    removed: list[str] = field(default_factory=list)
    ts: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": FrameKind.DELTA.value,
            "session_id": self.session_id,
            "seq": self.seq,
            "ts": self.ts,
            "schema": SCHEMA_VERSION,
            "changes": self.changes,
            "removed": self.removed,
        }


@dataclass(frozen=True)
class EventsFrame:
    session_id: str
    seq: int
    events: list[dict[str, Any]]      # IntelligenceEvent.as_dict() entries
    critical: bool = False
    ts: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": FrameKind.EVENTS.value,
            "session_id": self.session_id,
            "seq": self.seq,
            "ts": self.ts,
            "schema": SCHEMA_VERSION,
            "critical": self.critical,
            "events": self.events,
        }


@dataclass(frozen=True)
class TelemetryFrame:
    session_id: str
    seq: int
    driver_number: int
    samples: list[dict[str, Any]]
    ts: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": FrameKind.TELEMETRY.value,
            "session_id": self.session_id,
            "seq": self.seq,
            "ts": self.ts,
            "schema": SCHEMA_VERSION,
            "driver": self.driver_number,
            "samples": self.samples,
        }
