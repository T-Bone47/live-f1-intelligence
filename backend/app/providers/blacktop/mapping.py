"""Blacktop raw rows -> canonical models (provenance class B always).

Rules below come from the real 2023 Singapore GP responses, cross-checked
field by field against Jolpica and OpenF1 on 2026-09-25:

- Results use `carNumber` (the number raced in that session). In the 2023
  results rows `driver.number` equals it for all 19/20 drivers, but the
  STANDINGS `number` is the driver's current number (Verstappen and
  Ricciardo both 3 in 2023) -> standings `number` is never used.
- `laps` for a retirement is Jolpica + 1 (laps started) -> laps_completed is
  only set for classified finishers (status "OK").
- `displayTime` is "DNF" for retirements -> not a time; status carries it.
- quali `sectors` are NOT the best lap's sectors (SAI s1 38.085 vs the
  real 26.717 of lap 19) -> deliberately not mapped.
- No round numbers and no wins in standings -> None, never derived.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.enums import ProvenanceClass, ProviderName, SessionStatus, SessionType
from app.core.models import QualifyingResult, RaceResult, SessionInfo, StandingsEntry

_SESSION_TYPES = {
    "practice": SessionType.PRACTICE,
    "qualifying": SessionType.QUALIFYING,
    "sprint_qualifying": SessionType.SPRINT_QUALI,
    "sprint": SessionType.SPRINT,
    "race": SessionType.RACE,
}


def _prov(ts: datetime | None = None) -> dict:
    return {
        "provider": ProviderName.BLACKTOP.value,
        "source_timestamp": ts.isoformat() if ts else None,
        "provenance_class": ProvenanceClass.B.value,
    }


def _ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)  # 3.11 parses a trailing Z
    except ValueError:
        return None


def _int(raw: Any) -> int | None:
    text = str(raw) if raw is not None else ""
    return int(text) if text.isdigit() else None


def _float(raw: Any) -> float | None:
    try:
        return float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def event_to_sessions(event: dict[str, Any]) -> list[SessionInfo]:
    """One SessionInfo per schedule entry; an event without sessions yields none."""
    location = event.get("location") or {}
    country = location.get("country") or {}
    season = (event.get("season") or {}).get("year")
    year = int(season) if season else _int(str(event.get("dateStart") or "")[:4])
    event_cancelled = event.get("status") == "cancelled"
    out: list[SessionInfo] = []
    for sess in event.get("schedule") or []:
        start, end = _ts(sess.get("startTime")), _ts(sess.get("endTime"))
        cancelled = event_cancelled or sess.get("status") == "cancelled"
        key = f"{event['id']}/{sess['id']}"
        out.append(SessionInfo(
            session_id=f"blacktop:{key}",
            provider=ProviderName.BLACKTOP,
            provider_session_key=key,
            provider_meeting_key=event["id"],
            meeting_name=event.get("name"),
            year=year,
            session_type=_SESSION_TYPES.get(str(sess.get("type")), SessionType.UNKNOWN),
            session_name=sess.get("name"),
            circuit_short_name=location.get("name"),
            country_code=country.get("threeCode"),
            country_name=country.get("name"),
            location=location.get("city"),
            date_start=start,
            date_end=end,
            is_cancelled=cancelled,
            status=(SessionStatus.CANCELLED if cancelled
                    else SessionInfo.derive_status(start, end, False)),
            provenance=_prov(start),  # type: ignore[arg-type]
        ))
    return out


def race_row_to_result(row: dict[str, Any], session_id: str) -> RaceResult:
    driver = row.get("driver") or {}
    team = row.get("team") or {}
    finished = row.get("status") == "OK"
    return RaceResult(
        session_id=session_id,
        driver_ref=str(driver.get("id") or "unknown"),
        driver_number=_int(row.get("carNumber")),
        family_name=driver.get("lastName"),
        constructor_ref=team.get("id"),
        position=_int(row.get("position")),
        status_text=row.get("status"),
        points=_float(row.get("points")),
        laps_completed=_int(row.get("laps")) if finished else None,
        finish_time_raw=row.get("displayTime") if finished else None,
        fastest_lap_raw=row.get("bestLapTime"),
        provenance=_prov(),  # type: ignore[arg-type]
    )


def quali_row_to_result(row: dict[str, Any], session_id: str) -> QualifyingResult:
    driver = row.get("driver") or {}
    team = row.get("team") or {}

    def q(key: str) -> str | None:
        v = row.get(key)
        return str(v) if v else None

    return QualifyingResult(
        session_id=session_id,
        driver_ref=str(driver.get("id") or "unknown"),
        driver_number=_int(row.get("carNumber")),
        constructor_ref=team.get("id"),
        position=_int(row.get("position")),
        q1_raw=q("q1Time"),
        q2_raw=q("q2Time"),
        q3_raw=q("q3Time"),
        provenance=_prov(),  # type: ignore[arg-type]
    )


def standing_row_to_entry(row: dict[str, Any], season: int) -> StandingsEntry:
    teams = row.get("teams") or []
    return StandingsEntry(
        season=season,
        round_after=None,  # upstream does not say which round the table is after
        driver_ref=str(row.get("id") or "unknown"),
        family_name=row.get("lastName"),
        constructor_ref=teams[0].get("id") if len(teams) == 1 else None,
        position=_int(row.get("position")),
        points=_float(row.get("points")),
        wins=None,  # not provided upstream
        provenance=_prov(),  # type: ignore[arg-type]
    )
