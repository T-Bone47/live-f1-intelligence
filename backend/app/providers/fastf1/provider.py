"""FastF1 provider: historical/high-resolution data, ALWAYS class B.

FastF1 is a post-session analysis library - it is NOT a live provider and is
never presented as one. Verified in Phase 1.5: fastf1 3.8.3 installs and its
Jolpica-backed schedule loads. Full session loads (laps/telemetry) are heavy
network operations and were NOT executed this phase; the adapter therefore
works on duck-typed session objects so tests run without network.

Provenance: every emitted item is class B_HISTORICAL. Never live.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, AsyncIterator

from app.core.enums import Compound, ProvenanceClass, ProviderName
from app.core.models import SessionInfo
from app.providers.base import Capabilities, Channel, RawItem

log = logging.getLogger(__name__)


class FastF1Error(RuntimeError):
    pass


def _require_fastf1():  # noqa: ANN202
    try:
        import fastf1  # noqa: PLC0415

        return fastf1
    except ImportError as exc:  # pragma: no cover - optional dep
        raise FastF1Error(
            "fastf1 not installed; add the 'fastf1' extra to use this provider"
        ) from exc


def _ts(value: Any) -> datetime | None:
    """Coerce pandas.Timestamp / datetime / str to tz-aware UTC datetime."""
    if value is None:
        return None
    ts = getattr(value, "to_pydatetime", None)
    dt = ts() if callable(ts) else value
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def lap_row_to_raw(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a FastF1 Laps row (dict-like) into our LAP payload shape.

    Field mapping follows FastF1 3.x Laps columns: DriverNumber, LapNumber,
    LapStartTime/LapTime, Sector1/2/3Time, Stint, Compound, TyreLife,
    IsAccurate, TrackStatus, Deleted/DeletedReason (where present).
    Missing values stay None (pandas NaT/NaN coerced) - never zero-filled.
    """

    def num(v: Any) -> float | None:
        try:
            f = float(v)
            return None if f != f else f  # NaN check
        except (TypeError, ValueError):
            return None

    def sec(v: Any) -> float | None:
        td = getattr(v, "total_seconds", None)
        if td is not None and callable(td):
            return v.total_seconds()
        return num(v)

    lap_start = _ts(row.get("LapStartTime"))
    return {
        "driver_number": int(num(row.get("DriverNumber")) or 0),
        "lap_number": int(num(row.get("LapNumber")) or 0),
        "date_start": lap_start.isoformat() if lap_start else None,
        "lap_duration": sec(row.get("LapTime")),
        "duration_sector_1": sec(row.get("Sector1Time")),
        "duration_sector_2": sec(row.get("Sector2Time")),
        "duration_sector_3": sec(row.get("Sector3Time")),
        "is_pit_out_lap": bool(row.get("PitOutTime")) if row.get("PitOutTime") is not None else None,
        "compound": (str(row.get("Compound")) if row.get("Compound") else None),
        "tyre_life": num(row.get("TyreLife")),
        "stint": int(num(row.get("Stint")) or 0),
        "track_status": row.get("TrackStatus"),
        "deleted": bool(row.get("Deleted")) if row.get("Deleted") is not None else None,
        "deleted_reason": row.get("DeletedReason"),
        "is_accurate": bool(row.get("IsAccurate")) if row.get("IsAccurate") is not None else None,
    }


class FastF1Provider:
    name = "fastf1"

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = cache_dir

    def capabilities(self) -> Capabilities:
        return Capabilities(
            historical=True,
            laps=True,
            sectors=True,
            telemetry_car=True,
            telemetry_location=True,
            stints=True,
            weather=True,
            race_control=True,
            session_discovery=True,
            schedule=True,
            mini_segments=False,
            timing_intervals=False,
            positions=True,
            verified=(
                "fastf1 3.8.3 import + 2026 schedule load (Phase 1.5)",
                "post-session parsing pipeline widely documented",
            ),
            assumed=(
                "laps/telemetry DataFrame column shapes per FastF1 3.x docs",
                "race-control/track-status availability per docs",
            ),
            notes=(
                "HISTORICAL ONLY - never a live source; all output class B",
                "full session load NOT executed in Phase 1.5 (heavy); adapter "
                "is duck-typed and unit-tested offline",
                "requires local cache dir at runtime",
            ),
        )

    async def discover_sessions(self, year: int | None = None) -> list[SessionInfo]:
        """Load the FastF1/Jolpica event schedule (light, verified working)."""
        import asyncio

        ff1 = _require_fastf1()

        def _load() -> list[SessionInfo]:
            if self._cache_dir:
                ff1.Cache.enable_cache(self._cache_dir)
            sched = ff1.get_event_schedule(year or datetime.now().year)
            out: list[SessionInfo] = []
            for _, ev in sched.iterrows():
                prov = {
                    "provider": ProviderName.FASTF1.value,
                    "source_timestamp": _ts(ev.get("EventDate")).isoformat()
                    if _ts(ev.get("EventDate")) else None,
                    "provenance_class": ProvenanceClass.B.value,
                }
                out.append(
                    SessionInfo.model_validate({
                        "session_id": f"fastf1:{int(ev['RoundNumber'])}-{ev['EventName']}",
                        "provider": ProviderName.FASTF1.value,
                        "provider_session_key": f"{int(ev['RoundNumber'])}",
                        "provider_meeting_key": str(int(ev["RoundNumber"])),
                        "meeting_name": ev.get("EventName"),
                        "year": int(ev.get("Year", 0)) or None,
                        "session_type": "RACE",
                        "session_name": ev.get("EventName"),
                        "circuit_short_name": ev.get("Location"),
                        "country_code": ev.get("CountryAbbreviation"),
                        "country_name": ev.get("Country"),
                        "location": ev.get("Location"),
                        "date_start": _ts(ev.get("EventDate")),
                        "status": "FINISHED",
                        "provenance": prov,
                    })
                )
            return out

        return await asyncio.to_thread(_load)

    async def resolve_session(self, session_ref: str) -> SessionInfo:
        sessions = await self.discover_sessions()
        for s in sessions:
            if s.session_id == session_ref or s.provider_session_key == session_ref:
                return s
        raise FastF1Error(f"fastf1 session {session_ref} not found in schedule")

    async def run(self, session: SessionInfo, loaded_session: Any | None = None) -> AsyncIterator[RawItem]:
        """Emit class-B RawItems from a LOADED FastF1 Session object.

        `loaded_session` must be a fastf1.core.Session with .laps populated
        (caller decides when the expensive load happens). Duck-typed access
        only: iterrows() over laps + attribute reads.
        """
        cls = ProvenanceClass.B
        if loaded_session is None:
            log.info("fastf1: no loaded session supplied - nothing to emit")
            return

        laps = getattr(loaded_session, "laps", None)
        if laps is not None:
            for _, row in laps.iterrows():
                yield RawItem(Channel.LAP, lap_row_to_raw(row.to_dict()), None, cls)

        # weather rows (duck-typed DataFrame)
        weather = getattr(loaded_session, "weather_data", None) or getattr(
            loaded_session, "weather", None
        )
        if weather is not None:
            for _, w in weather.iterrows():
                d = w.to_dict()
                ts = _ts(d.get("Time")) or _ts(d.get("Date"))
                yield RawItem(Channel.WEATHER, {
                    "date": ts.isoformat() if ts else None,
                    "air_temperature": d.get("AirTemp"),
                    "track_temperature": d.get("TrackTemp"),
                    "humidity": d.get("Humidity"),
                    "pressure": d.get("Pressure"),
                    "rainfall": d.get("Rainfall"),
                    "wind_direction": d.get("WindDirection"),
                    "wind_speed": d.get("WindSpeed"),
                }, ts, cls)
