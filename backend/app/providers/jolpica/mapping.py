"""Jolpica raw Ergast-shaped rows -> canonical models (class B always)."""

from __future__ import annotations

from datetime import datetime, time as dtime, timezone
from typing import Any

from app.core.enums import ProvenanceClass, ProviderName, SessionStatus, SessionType
from app.core.models import (
    QualifyingResult,
    RaceResult,
    SessionInfo,
    StandingsEntry,
)


class MappingError(ValueError):
    pass


def _prov(ts: datetime | None) -> dict:
    return {
        "provider": ProviderName.JOLPICA.value,
        "source_timestamp": ts.isoformat() if ts else None,
        "provenance_class": ProvenanceClass.B.value,
    }


def _parse_date_time(date_raw: str | None, time_raw: str | None) -> datetime | None:
    if not date_raw:
        return None
    try:
        d = datetime.fromisoformat(date_raw)
    except ValueError:
        return None
    if time_raw:
        try:
            t = dtime.fromisoformat(time_raw.replace("Z", "+00:00"))
            return datetime.combine(d.date(), t, tzinfo=timezone.utc)
        except ValueError:
            pass
    return d.replace(tzinfo=timezone.utc)


def race_row_to_session(race: dict[str, Any]) -> SessionInfo:
    """Map a Jolpica/Ergast Races[] row to a SCHEDULE-class SessionInfo."""
    round_no = int(race.get("round", 0))
    date_start = _parse_date_time(race.get("date"), race.get("time"))
    name = race.get("raceName") or "UNKNOWN"
    circuit = (race.get("Circuit") or {})
    location = (circuit.get("Location") or {})
    country = location.get("country")
    locality = location.get("locality")
    season = int(race.get("season", 0))
    prov = _prov(date_start)
    return SessionInfo(
        session_id=f"jolpica:{season}-r{round_no}",
        provider=ProviderName.JOLPICA,
        provider_session_key=f"{season}-r{round_no}",
        provider_meeting_key=str(season),
        meeting_name=name,
        year=season or None,
        session_type=SessionType.RACE,
        session_name=name,
        circuit_short_name=circuit.get("circuitName"),
        country_code=None,
        country_name=country,
        location=locality,
        date_start=date_start,
        date_end=None,
        status=SessionStatus.SCHEDULED if (date_start and date_start > datetime.now(tz=timezone.utc)) else SessionStatus.FINISHED,
        provenance=prov,  # type: ignore[arg-type]
    )


def result_row_to_race_result(row: dict[str, Any], session_id: str) -> RaceResult:
    driver = row.get("Driver") or {}
    constructor = row.get("Constructor") or {}
    time_obj = row.get("Time") or {}
    fastest = row.get("FastestLap") or {}
    fl_time = (fastest.get("Time") or {}).get("time")
    pos_raw = row.get("position")
    try:
        position = int(pos_raw) if pos_raw is not None else None
    except ValueError:
        position = None  # 'N' DNF placeholders stay unnumbered
    points_raw = row.get("points")
    laps_raw = row.get("laps")
    return RaceResult(
        session_id=session_id,
        driver_ref=str(driver.get("driverId") or "unknown"),
        driver_number=int(driver["number"]) if str(driver.get("number") or "").isdigit() else None,
        family_name=driver.get("familyName"),
        constructor_ref=str(constructor.get("constructorId")) if constructor.get("constructorId") else None,
        position=position,
        status_text=row.get("status"),
        points=float(points_raw) if points_raw not in (None, "") else None,
        laps_completed=int(laps_raw) if str(laps_raw or "").isdigit() else None,
        finish_time_raw=time_obj.get("time"),
        fastest_lap_raw=fl_time,
        provenance=_prov(None),  # type: ignore[arg-type]
    )


def quali_row_to_result(row: dict[str, Any], session_id: str) -> QualifyingResult:
    driver = row.get("Driver") or {}
    constructor = row.get("Constructor") or {}
    pos_raw = row.get("position")

    def q(key: str) -> str | None:
        v = row.get(key)
        return str(v) if v else None

    return QualifyingResult(
        session_id=session_id,
        driver_ref=str(driver.get("driverId") or "unknown"),
        driver_number=int(driver["number"]) if str(driver.get("number") or "").isdigit() else None,
        constructor_ref=str(constructor.get("constructorId")) if constructor.get("constructorId") else None,
        position=int(pos_raw) if str(pos_raw or "").isdigit() else None,
        q1_raw=q("Q1"),
        q2_raw=q("Q2"),
        q3_raw=q("Q3"),
        provenance=_prov(None),  # type: ignore[arg-type]
    )


def standing_row_to_entry(row: dict[str, Any], season: int) -> StandingsEntry:
    driver = row.get("Driver") or {}
    constructor = (row.get("Constructors") or [{}])[0]
    pos_raw = row.get("position")
    pts_raw = row.get("points")
    wins_raw = row.get("wins")
    return StandingsEntry(
        season=season,
        round_after=int(row.get("_round", -1)) if row.get("_round") is not None else -1,
        driver_ref=str(driver.get("driverId") or "unknown"),
        family_name=driver.get("familyName"),
        constructor_ref=str(constructor.get("constructorId")) if constructor.get("constructorId") else None,
        position=int(pos_raw) if str(pos_raw or "").isdigit() else None,
        points=float(pts_raw) if pts_raw not in (None, "") else None,
        wins=int(wins_raw) if str(wins_raw or "").isdigit() else None,
        provenance=_prov(None),  # type: ignore[arg-type]
    )
