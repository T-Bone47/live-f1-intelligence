"""Provider abstraction.

Providers sit at the edge of the system. They yield *raw vendor items* tagged
with a channel; normalization into canonical models happens downstream
(app.ingest.normalize). Nothing above this layer may know vendor shapes.

Capability honesty rule (Phase 1.5): a provider must NOT claim a capability
merely because the category exists here. Every True must be backed by verified
behavior or explicitly flagged in `unverified_claims`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import AsyncIterator, Protocol

from app.core.enums import ProvenanceClass
from app.core.models import SessionInfo


class Channel(str, Enum):
    """Vendor-agnostic stream channels a provider can emit."""

    SESSION_META = "SESSION_META"
    DRIVER_LIST = "DRIVER_LIST"
    LAP = "LAP"
    CAR_DATA = "CAR_DATA"
    LOCATION = "LOCATION"
    STINT = "STINT"
    PIT = "PIT"
    WEATHER = "WEATHER"
    RACE_CONTROL = "RACE_CONTROL"
    POSITION = "POSITION"
    INTERVALS = "INTERVALS"
    TEAM_RADIO = "TEAM_RADIO"  # reserved; not implemented Phase 1
    RESULTS = "RESULTS"  # historical results (Jolpica/FastF1)
    STANDINGS = "STANDINGS"  # championship standings (Jolpica)
    SCHEDULE = "SCHEDULE"  # season schedule (Jolpica)
    LAP_CORRECTION = "LAP_CORRECTION"  # tombstones derived from RCM


@dataclass(frozen=True)
class Capabilities:
    """Explicit capability descriptor: absent == unsupported (class F).

    Fields are grouped by concern. `verified` / `assumed` notes let a provider
    distinguish what it has PROVEN from what it EXPECTS - consumers may treat
    assumed claims as unavailable until first successful delivery.
    """

    # lifecycle
    session_discovery: bool = False
    live: bool = False
    historical: bool = False

    # timing & race data
    timing_intervals: bool = False
    laps: bool = False
    sectors: bool = False
    mini_segments: bool = False
    positions: bool = False

    # telemetry
    telemetry_car: bool = False
    telemetry_location: bool = False

    # tyres/pits
    stints: bool = False
    pits: bool = False

    # environment/officiating
    weather: bool = False
    race_control: bool = False
    lap_corrections: bool = False

    # reference/history extras
    results: bool = False
    standings: bool = False
    schedule: bool = False
    team_radio: bool = False

    # epistemics
    verified: tuple[str, ...] = field(default_factory=tuple)
    assumed: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for k, v in self.__dict__.items():
            if isinstance(v, tuple):
                out[k] = list(v)
            else:
                out[k] = v
        return out


@dataclass
class RawItem:
    """A single raw vendor record flowing into the pipeline."""

    channel: Channel
    payload: dict  # verbatim vendor payload (JSON-shaped), or {"__envelope": ...}
    source_timestamp: datetime | None
    provenance_class: ProvenanceClass


class DataProvider(Protocol):
    """Every provider implements this surface. Replay included."""

    name: str

    def capabilities(self) -> Capabilities: ...

    async def discover_sessions(self, year: int | None = None) -> list[SessionInfo]:
        """List known sessions (schedule)."""
        ...

    async def resolve_session(self, session_ref: str) -> SessionInfo:
        """Resolve 'latest', a provider key, or a canonical id to SessionInfo."""
        ...

    def run(self, session: SessionInfo) -> AsyncIterator[RawItem]:
        """Yield RawItems for the session until exhausted or cancelled.

        Live providers run until cancelled; historical/replay providers end
        when data is exhausted.
        """
        ...
