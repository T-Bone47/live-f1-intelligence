"""Canonical schemas (Phase 1).

Rules enforced here:
- Nullable means genuinely unknown/absent. Never substitute zeros or
  fabricated values for missing data.
- Every record carries Provenance: provider, class (A..F), source timestamp
  and ingestion timestamp are preserved end to end.
- These models are the ONLY interchange format above the provider layer.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import (
    Compound,
    DriverStatus,
    ProvenanceClass,
    ProviderName,
    RCMCategory,
    SessionStatus,
    SessionType,
)


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    source_timestamp: datetime | None = None
    ingestion_timestamp: datetime = Field(default_factory=utcnow)
    provenance_class: ProvenanceClass


class SessionInfo(BaseModel):
    """A discovered session (schedule + lifecycle facts known so far)."""

    session_id: str  # canonical: f"{provider}:{provider_session_key}"
    provider: ProviderName
    provider_session_key: str
    provider_meeting_key: str | None = None
    meeting_name: str | None = None
    year: int | None = None
    session_type: SessionType = SessionType.UNKNOWN
    session_name: str | None = None
    circuit_short_name: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    location: str | None = None
    gmt_offset: str | None = None
    date_start: datetime | None = None
    date_end: datetime | None = None
    is_cancelled: bool = False
    status: SessionStatus = SessionStatus.UNKNOWN
    provenance: Provenance

    @staticmethod
    def derive_status(
        date_start: datetime | None, date_end: datetime | None, is_cancelled: bool
    ) -> SessionStatus:
        """Heuristic: upstream exposes no explicit live status flag."""
        if is_cancelled:
            return SessionStatus.CANCELLED
        now = utcnow()
        if date_start and date_end:
            if now < date_start:
                return SessionStatus.SCHEDULED
            if date_start <= now <= date_end:
                return SessionStatus.LIVE
            return SessionStatus.FINISHED
        return SessionStatus.UNKNOWN


class Team(BaseModel):
    team_id: str  # slug, e.g. "mclaren"
    display_name: str
    colour_hex: str | None = None
    provenance: Provenance


class Driver(BaseModel):
    driver_id: str  # slug, e.g. "lando-norris" (stable across sessions)
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    name_acronym: str | None = Field(default=None, max_length=3)
    broadcast_name: str | None = None
    country_code: str | None = None  # nullable upstream (verified)
    headshot_url: str | None = None
    team: Team | None = None
    provenance: Provenance


class Lap(BaseModel):
    session_id: str
    driver_number: int
    lap_number: int
    started_at: datetime  # source timestamp of lap start
    duration_s: float | None = None  # null while in-progress / not reported
    sector1_s: float | None = None
    sector2_s: float | None = None
    sector3_s: float | None = None
    is_pit_out_lap: bool | None = None
    speed_traps: "SpeedTraps | None" = None
    deleted: bool = False  # tombstone; set by later RCM knowledge (future phase)
    provenance: Provenance


class SpeedTraps(BaseModel):
    i1_kph: int | None = None
    i2_kph: int | None = None
    st_kph: int | None = None
    fl_kph: int | None = None  # finish-line trap (not in OpenF1 laps; reserved)


class SectorTime(BaseModel):
    session_id: str
    driver_number: int
    lap_number: int
    sector_index: Literal[1, 2, 3]
    time_s: float | None = None
    # Mini-segment raw codes as delivered by the source. We store them verbatim;
    # interpretation (green/yellow/purple) is a later derived concern.
    segment_codes: list[int | None] | None = None
    provenance: Provenance


class TelemetryCarSample(BaseModel):
    session_id: str
    driver_number: int
    ts: datetime
    rpm: int | None = None
    speed_kph: int | None = None
    gear: int | None = None
    throttle_pct: float | None = None
    brake_pct: float | None = None  # source delivers 0/100 binary - preserved as-is
    drs: int | None = None  # raw code; verified nullable upstream

    @field_validator("throttle_pct", "brake_pct")
    @classmethod
    def _pct_range(cls, v: float | None) -> float | None:
        if v is None:
            return None
        return max(0.0, min(100.0, v))

    provenance: Provenance


class TelemetryLocationSample(BaseModel):
    session_id: str
    driver_number: int
    ts: datetime
    x: float | None = None
    y: float | None = None
    z: float | None = None
    provenance: Provenance


class TyreStint(BaseModel):
    session_id: str
    driver_number: int
    stint_number: int  # 1-based upstream (verified)
    compound: Compound = Compound.UNKNOWN
    lap_start: int | None = None
    lap_end: int | None = None
    tyre_age_at_start: int | None = None
    provenance: Provenance


class PitStop(BaseModel):
    session_id: str
    driver_number: int
    ts: datetime
    lap_number: int | None = None
    lane_duration_s: float | None = None
    stop_duration_s: float | None = None  # verified nullable upstream
    provenance: Provenance


class WeatherPoint(BaseModel):
    session_id: str
    ts: datetime
    air_temp_c: float | None = None
    track_temp_c: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    rainfall: bool | None = None
    wind_direction_deg: int | None = None
    wind_speed_mps: float | None = None  # upstream unit unconfirmed; stored verbatim
    provenance: Provenance


class RaceControlEvent(BaseModel):
    session_id: str
    ts: datetime
    category: RCMCategory = RCMCategory.UNKNOWN
    flag: str | None = None  # raw flag string (CLEAR/YELLOW/DOUBLE YELLOW/...)
    scope: str | None = None
    # NOTE: upstream `sector` here is a MARSHAL-POST sector number (>3 observed),
    # NOT a timing sector 1-3. Stored verbatim under marshal_sector.
    marshal_sector: int | None = None
    driver_number: int | None = None
    lap_number: int | None = None
    qualifying_phase: str | None = None
    message: str
    rcm_key: str  # stable hash for dedupe (upstream has no id)
    provenance: Provenance

    @staticmethod
    def make_key(ts: datetime, message: str) -> str:
        # Second granularity: upstream RCM timestamps carry no microseconds;
        # this keeps dedupe stable across re-delivery with sub-second jitter.
        basis = f"{ts.replace(microsecond=0).isoformat()}|{message}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


class PositionUpdate(BaseModel):
    """Position-change events only (upstream emits on change, verified)."""

    session_id: str
    driver_number: int
    ts: datetime
    position: int
    provenance: Provenance


class TimingInterval(BaseModel):
    """Gap-to-leader / interval samples (~4 s cadence upstream, verified).

    EMPIRICAL: gap_to_leader is MIXED-TYPE upstream - floats for cars on the
    lead lap, strings like '+1 LAP' for lapped traffic. The numeric value goes
    to gap_to_leader_s; the raw string is preserved in gap_raw (never dropped,
    never coerced to a fake number).
    """

    session_id: str
    driver_number: int
    ts: datetime
    gap_to_leader_s: float | None = None
    gap_raw: str | None = None  # verbatim non-numeric upstream value e.g. '+1 LAP'
    interval_s: float | None = None
    provenance: Provenance


Lap.model_rebuild()


# ---------------------------------------------------- corrections (Phase 1.5)


class CorrectionKind(str, Enum):
    LAP_DELETED = "LAP_DELETED"
    LAP_REINSTATED = "LAP_REINSTATED"


class LapCorrection(BaseModel):
    """Explicit tombstone/correction for a previously-recorded lap.

    History is NEVER silently overwritten: the original lap row/event stays,
    and this correction is a separate, auditable record. `laps.deleted` is a
    projection applied from these records.
    VERIFIED upstream pattern (2026 Dutch GP):
      "CAR 27 (HUL) TIME 1:23.646 DELETED - TRACK LIMITS AT TURN 3 LAP 5"
    """

    session_id: str
    driver_number: int
    lap_number: int
    kind: CorrectionKind
    reason: str | None = None
    deleted_time_raw: str | None = None  # verbatim time string from message
    turn: int | None = None
    rcm_key: str | None = None  # link to source RaceControlEvent
    provenance: Provenance


# ------------------------------------------- reference/history (Phase 1.5)
# Cross-source identity note: Jolpica/F1DB use Ergast-style refs
# ("antonelli"); we store them verbatim in *_ref fields. Reconciliation to our
# canonical driver_id happens via name normalization at analysis time - never
# by guessing.


class RaceResult(BaseModel):
    session_id: str
    driver_ref: str
    driver_number: int | None = None
    family_name: str | None = None
    constructor_ref: str | None = None
    position: int | None = None
    status_text: str | None = None
    points: float | None = None
    laps_completed: int | None = None
    finish_time_raw: str | None = None
    fastest_lap_raw: str | None = None
    provenance: Provenance


class QualifyingResult(BaseModel):
    session_id: str
    driver_ref: str
    driver_number: int | None = None
    constructor_ref: str | None = None
    position: int | None = None
    q1_raw: str | None = None
    q2_raw: str | None = None
    q3_raw: str | None = None
    provenance: Provenance


class StandingsEntry(BaseModel):
    season: int
    round_after: int | None = None
    driver_ref: str
    family_name: str | None = None
    constructor_ref: str | None = None
    position: int | None = None
    points: float | None = None
    wins: int | None = None
    provenance: Provenance


CanonicalModel = (
    SessionInfo | Driver | Team | Lap | SectorTime
    | TelemetryCarSample | TelemetryLocationSample | TyreStint | PitStop
    | WeatherPoint | RaceControlEvent | PositionUpdate | TimingInterval
    | LapCorrection | RaceResult | QualifyingResult | StandingsEntry
)
