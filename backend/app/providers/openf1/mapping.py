"""OpenF1 raw payloads -> canonical models.

Every function is tolerant: malformed records raise NormalizationError (counted
by the pipeline) instead of crashing ingestion. Unknown enum values map to
*_UNKNOWN. Missing data stays None - never fabricated.

Field notes are EMPIRICAL (verified 2026-08-23 against session 11353,
2026 Dutch GP Race):
- laps: `lap_duration` (NOT lap_time); sector durations in seconds; speed traps
  i1/i2/st; segments_sector_* mini-sector code arrays with nulls.
- car_data: `drs` nullable; brake/throttle 0..100; n_gear int.
- stints: stint_number starts at 1.
- pit: stop_duration nullable; pit_duration == lane_duration observed.
- race_control: no id -> key = sha256(date|message); `sector` is marshal-post
  number (values >3 observed), NOT timing sector.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.core.enums import Compound, ProviderName, RCMCategory, SessionType, enum_or_unknown
from app.core.models import (
    Driver,
    Lap,
    PitStop,
    PositionUpdate,
    Provenance,
    RaceControlEvent,
    SectorTime,
    SessionInfo,
    SpeedTraps,
    Team,
    TelemetryCarSample,
    TelemetryLocationSample,
    TimingInterval,
    TyreStint,
    WeatherPoint,
)

log = logging.getLogger(__name__)

PROVIDER = ProviderName.OPENF1


class NormalizationError(ValueError):
    """Raised when a vendor record cannot be normalized; counted, never fatal."""


def parse_ts(raw: Any) -> datetime:
    """Parse an upstream ISO timestamp or fail loudly."""
    if not isinstance(raw, str):
        raise NormalizationError(f"timestamp missing/malformed: {raw!r}")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NormalizationError(f"bad ISO timestamp {raw!r}") from exc


def _prov(ts: datetime | None, cls=...) -> Provenance:  # type: ignore[assignment]
    from app.core.enums import ProvenanceClass

    return Provenance(
        provider=PROVIDER,
        source_timestamp=ts,
        provenance_class=ProvenanceClass.B if cls is ... else cls,
    )


def slugify(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "-" for ch in text.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


# ---------------------------------------------------------------- sessions ---

SESSION_TYPE_MAP = {
    "practice": SessionType.PRACTICE,
    "qualifying": SessionType.QUALIFYING,
    "sprint qualifying": SessionType.SPRINT_QUALI,
    "sprint shootout": SessionType.SPRINT_SHOOTOUT,
    "sprint": SessionType.SPRINT,
    "race": SessionType.RACE,
}


def map_session_type(raw: str | None) -> SessionType:
    if not raw:
        return SessionType.UNKNOWN
    return SESSION_TYPE_MAP.get(raw.strip().lower(), SessionType.UNKNOWN)


def to_session(row: dict[str, Any], provenance_class=...) -> SessionInfo:
    try:
        sk = row["session_key"]
        date_start_raw = row.get("date_start")
        date_end_raw = row.get("date_end")
        date_start = parse_ts(date_start_raw) if date_start_raw else None
        date_end = parse_ts(date_end_raw) if date_end_raw else None
        cancelled = bool(row.get("is_cancelled", False))
        prov = _prov(date_start, provenance_class)
        return SessionInfo(
            session_id=f"{PROVIDER.value}:{sk}",
            provider=PROVIDER,
            provider_session_key=str(sk),
            provider_meeting_key=str(row["meeting_key"]) if row.get("meeting_key") else None,
            year=row.get("year"),
            session_type=map_session_type(row.get("session_type")),
            session_name=row.get("session_name"),
            circuit_short_name=row.get("circuit_short_name"),
            country_code=row.get("country_code"),
            country_name=row.get("country_name"),
            location=row.get("location"),
            gmt_offset=row.get("gmt_offset"),
            date_start=date_start,
            date_end=date_end,
            is_cancelled=cancelled,
            status=SessionInfo.derive_status(date_start, date_end, cancelled),
            provenance=prov,
        )
    except (KeyError, TypeError) as exc:
        raise NormalizationError(f"session row malformed: {exc}") from exc


# ----------------------------------------------------------------- drivers ---

_TEAM_NAME_FIXES = {"kick sauber": "sauber", "alpine": "alpine"}


def to_team(driver_row: dict[str, Any], provenance_class=...) -> Team | None:
    team_name = driver_row.get("team_name")
    if not team_name:
        return None
    colour = driver_row.get("team_colour")
    return Team(
        team_id=slugify(_TEAM_NAME_FIXES.get(team_name.strip().lower(), team_name.strip())),
        display_name=team_name.strip(),
        colour_hex=(colour if isinstance(colour, str) and colour.strip() else None),
        provenance=_prov(None, provenance_class),
    )


def to_driver(row: dict[str, Any], provenance_class=...) -> Driver:
    full = row.get("full_name")
    number = row.get("driver_number")
    if not full or number is None:
        raise NormalizationError(f"driver row missing name/number: {row!r}")
    base_slug = slugify(full)
    driver_id = f"{base_slug}-{int(number)}"  # number disambiguates same-name cases
    acronym = row.get("name_acronym")
    return Driver(
        driver_id=driver_id,
        full_name=full,
        first_name=row.get("first_name") or None,
        last_name=row.get("last_name") or None,
        name_acronym=acronym[:3] if isinstance(acronym, str) and acronym else None,
        broadcast_name=row.get("broadcast_name") or None,
        country_code=(row.get("country_code") or None),  # verified nullable
        headshot_url=row.get("headshot_url") or None,
        team=to_team(row, provenance_class),
        provenance=_prov(None, provenance_class),
    )


# -------------------------------------------------------------------- laps ---

_OPT_FLOATS_LAP = ("duration_sector_1", "duration_sector_2", "duration_sector_3")


def to_lap(row: dict[str, Any], session_id: str, provenance_class=...) -> tuple[Lap, list[SectorTime]]:
    ts = parse_ts(row.get("date_start"))
    prov = _prov(ts, provenance_class)

    def opt_float(key: str) -> float | None:
        v = row.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError) as exc:
            raise NormalizationError(f"lap field {key} malformed: {v!r}") from exc

    lap_duration = opt_float("lap_duration")
    s1, s2, s3 = (opt_float(k) for k in _OPT_FLOATS_LAP)
    lap = Lap(
        session_id=session_id,
        driver_number=int(row["driver_number"]),
        lap_number=int(row["lap_number"]),
        started_at=ts,
        duration_s=lap_duration,
        sector1_s=s1,
        sector2_s=s2,
        sector3_s=s3,
        is_pit_out_lap=row.get("is_pit_out_lap"),
        speed_traps=SpeedTraps(
            i1_kph=_opt_int(row, "i1_speed"),
            i2_kph=_opt_int(row, "i2_speed"),
            st_kph=_opt_int(row, "st_speed"),
        ),
        provenance=prov,
    )
    sectors = []
    for idx, val in ((1, s1), (2, s2), (3, s3)):
        seg_key = f"segments_sector_{idx}"
        segments = row.get(seg_key)
        sectors.append(
            SectorTime(
                session_id=session_id,
                driver_number=int(row["driver_number"]),
                lap_number=int(row["lap_number"]),
                sector_index=idx,
                time_s=val,
                segment_codes=list(segments) if isinstance(segments, list) else None,
                provenance=prov,
            )
        )
    return lap, sectors


def _opt_int(row: dict[str, Any], key: str) -> int | None:
    v = row.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"field {key} malformed: {v!r}") from exc


# --------------------------------------------------------------- telemetry ---


def to_car_sample(row: dict[str, Any], session_id: str, provenance_class=...) -> TelemetryCarSample:
    ts = parse_ts(row.get("date"))
    prov = _prov(ts, provenance_class)
    return TelemetryCarSample(
        session_id=session_id,
        driver_number=int(row["driver_number"]),
        ts=ts,
        rpm=_opt_int(row, "rpm"),
        speed_kph=_opt_int(row, "speed"),
        gear=_opt_int(row, "n_gear"),
        throttle_pct=_opt_float_or_none(row, "throttle"),
        brake_pct=_opt_float_or_none(row, "brake"),
        drs=_opt_int(row, "drs"),  # verified nullable
        provenance=prov,
    )


def to_location_sample(row: dict[str, Any], session_id: str, provenance_class=...) -> TelemetryLocationSample:
    ts = parse_ts(row.get("date"))
    return TelemetryLocationSample(
        session_id=session_id,
        driver_number=int(row["driver_number"]),
        ts=ts,
        x=_opt_float_or_none(row, "x"),
        y=_opt_float_or_none(row, "y"),
        z=_opt_float_or_none(row, "z"),
        provenance=_prov(ts, provenance_class),
    )


def _opt_float_or_none(row: dict[str, Any], key: str) -> float | None:
    v = row.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"field {key} malformed: {v!r}") from exc


# ------------------------------------------------------------------ tyres ----

COMPOUND_MAP = {
    "SOFT": Compound.SOFT,
    "MEDIUM": Compound.MEDIUM,
    "HARD": Compound.HARD,
    "INTERMEDIATE": Compound.INTERMEDIATE,
    "WET": Compound.WET,
    "UNKNOWN": Compound.TEST_UNKNOWN,  # upstream uses UNKNOWN for test compounds
    "TEST_UNKNOWN": Compound.TEST_UNKNOWN,
}


def to_stint(row: dict[str, Any], session_id: str, provenance_class=...) -> TyreStint:
    compound_raw = row.get("compound")
    compound = COMPOUND_MAP.get(compound_raw, Compound.UNKNOWN) if compound_raw else Compound.UNKNOWN
    if compound is Compound.UNKNOWN and compound_raw:
        log.warning("unknown tyre compound %r mapped to UNKNOWN", compound_raw)
    return TyreStint(
        session_id=session_id,
        driver_number=int(row["driver_number"]),
        stint_number=int(row["stint_number"]),
        compound=compound,
        lap_start=_opt_int(row, "lap_start"),
        lap_end=_opt_int(row, "lap_end"),
        tyre_age_at_start=_opt_int(row, "tyre_age_at_start"),
        provenance=_prov(None, provenance_class),
    )


# ------------------------------------------------------------------- pits ----


def to_pit_stop(row: dict[str, Any], session_id: str, provenance_class=...) -> PitStop:
    ts = parse_ts(row.get("date"))
    lane = _opt_float_or_none(row, "lane_duration")
    if lane is None:
        lane = _opt_float_or_none(row, "pit_duration")
    return PitStop(
        session_id=session_id,
        driver_number=int(row["driver_number"]),
        ts=ts,
        lap_number=_opt_int(row, "lap_number"),
        lane_duration_s=lane,
        stop_duration_s=_opt_float_or_none(row, "stop_duration"),  # verified nullable
        provenance=_prov(ts, provenance_class),
    )


# ---------------------------------------------------------------- weather ----


def to_weather(row: dict[str, Any], session_id: str, provenance_class=...) -> WeatherPoint:
    ts = parse_ts(row.get("date"))
    rainfall = row.get("rainfall")
    return WeatherPoint(
        session_id=session_id,
        ts=ts,
        air_temp_c=_opt_float_or_none(row, "air_temperature"),
        track_temp_c=_opt_float_or_none(row, "track_temperature"),
        humidity_pct=_opt_float_or_none(row, "humidity"),
        pressure_hpa=_opt_float_or_none(row, "pressure"),
        rainfall=(bool(rainfall) if rainfall is not None else None),
        wind_direction_deg=_opt_int(row, "wind_direction"),
        wind_speed_mps=_opt_float_or_none(row, "wind_speed"),
        provenance=_prov(ts, provenance_class),
    )


# ----------------------------------------------------------- race control ----


def to_rcm(row: dict[str, Any], session_id: str, provenance_class=...) -> RaceControlEvent:
    ts = parse_ts(row.get("date"))
    message = row.get("message")
    if not message or not isinstance(message, str):
        raise NormalizationError(f"rcm missing message: {row!r}")
    return RaceControlEvent(
        session_id=session_id,
        ts=ts,
        category=enum_or_unknown(RCMCategory, row.get("category")),
        flag=row.get("flag"),
        scope=row.get("scope"),
        marshal_sector=_opt_int(row, "sector"),
        driver_number=_opt_int(row, "driver_number"),
        lap_number=_opt_int(row, "lap_number"),
        qualifying_phase=row.get("qualifying_phase"),
        message=message,
        rcm_key=RaceControlEvent.make_key(ts, message),
        provenance=_prov(ts, provenance_class),
    )


# ------------------------------------------- positions / intervals -----------


def to_position(row: dict[str, Any], session_id: str, provenance_class=...) -> PositionUpdate:
    ts = parse_ts(row.get("date"))
    return PositionUpdate(
        session_id=session_id,
        driver_number=int(row["driver_number"]),
        ts=ts,
        position=int(row["position"]),
        provenance=_prov(ts, provenance_class),
    )


def _opt_float_lenient(row: dict[str, Any], key: str) -> tuple[float | None, str | None]:
    """Parse a numeric field that may legitimately carry non-numeric sentinels
    (verified: intervals gap_to_leader == '+1 LAP'). Returns (value, raw)."""
    v = row.get(key)
    if v is None:
        return None, None
    if isinstance(v, (int, float)):
        return float(v), None
    text = str(v).strip()
    try:
        return float(text), None
    except ValueError:
        return None, text  # preserve verbatim; never fabricate


def to_interval(row: dict[str, Any], session_id: str, provenance_class=...) -> TimingInterval:
    ts = parse_ts(row.get("date"))
    gap, gap_raw = _opt_float_lenient(row, "gap_to_leader")
    interval, _interval_raw = _opt_float_lenient(row, "interval")
    return TimingInterval(
        session_id=session_id,
        driver_number=int(row["driver_number"]),
        ts=ts,
        gap_to_leader_s=gap,
        gap_raw=gap_raw,
        interval_s=interval,
        provenance=_prov(ts, provenance_class),
    )


def safe(fn, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
    """Run a mapping fn, converting pydantic errors into NormalizationError."""
    try:
        return fn(*args, **kwargs)
    except NormalizationError:
        raise
    except ValidationError as exc:
        raise NormalizationError(str(exc.errors()[:3])) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise NormalizationError(f"{type(exc).__name__}: {exc}") from exc
