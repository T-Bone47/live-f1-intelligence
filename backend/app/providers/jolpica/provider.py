"""Jolpica provider: schedules, results, qualifying results, standings.

Purpose (Phase 1.5): historical/reference data ONLY - never live telemetry.
All emitted provenance is class B. Capabilities reflect verified behavior
(2026 schedule + standings verified against the real API on 2026-08-24).
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import SessionInfo
from app.providers.base import Capabilities, Channel, RawItem
from app.providers.jolpica.client import JolpicaClient, JolpicaError  # noqa: F401
from app.providers.jolpica.mapping import (
    quali_row_to_result,
    race_row_to_session,
    result_row_to_race_result,
    standing_row_to_entry,
)

log = logging.getLogger(__name__)


class JolpicaProvider:
    name = "jolpica"

    def __init__(self, client: JolpicaClient | None = None) -> None:
        self._client = client or JolpicaClient()

    def capabilities(self) -> Capabilities:
        return Capabilities(
            session_discovery=True,
            historical=True,
            schedule=True,
            results=True,
            standings=True,
            verified=(
                "2026 season schedule served (23 races)",
                "current driverStandings served",
            ),
            assumed=("qualifying/round-results shapes per Ergast compatibility",),
            notes=(
                "NOT live: updates committed weekly post-session",
                "Ergast-style refs stored verbatim; reconcile to canonical "
                "driver ids by name at analysis time",
                "limits: documented 4 rps / 500 rpm unauth; client defaults "
                "conservative",
            ),
        )

    async def discover_sessions(self, year: int | None = None) -> list[SessionInfo]:
        season = year if year is not None else "current"
        try:
            races = await self._client.season_schedule(season)
        except JolpicaError as exc:
            log.error("jolpica discovery failed: %s", exc)
            return []
        return [race_row_to_session(r) for r in races]

    async def resolve_session(self, session_ref: str) -> SessionInfo:
        # 'jolpica:2026-r14' style
        raw = session_ref.removeprefix("jolpica:")
        season, rnd = raw.split("-r")
        races = await self._client.season_schedule(season)
        for r in races:
            if str(r.get("round")) == str(int(rnd)):
                return race_row_to_session(r)
        raise JolpicaError(f"jolpica session {session_ref} not found")

    async def run(self, session: SessionInfo) -> AsyncIterator[RawItem]:
        """Yield schedule + results + standings for the referenced season.

        Jolpica has no streaming concept: run() emits its historical payload
        then completes. Season derived from the resolved session key.
        """
        cls = ProvenanceClass.B
        raw = session.provider_session_key
        season = raw.split("-")[0] if "-" in raw else raw
        yield RawItem(Channel.SCHEDULE, {"season": season}, None, cls)

        try:
            for r in await self._client.season_schedule(season):
                if str(session.provider_session_key).endswith(f"-r{r.get('round')}"):
                    yield RawItem(Channel.SESSION_META,
                                  self._schedule_payload(r), None, cls)
            round_no = raw.split("-r")[1] if "-r" in raw else None
            if round_no:
                for row in await self._client.race_results(season, round_no):
                    yield RawItem(Channel.RESULTS, {"kind": "race", "row": row}, None, cls)
                for row in await self._client.qualifying_results(season, round_no):
                    yield RawItem(Channel.RESULTS, {"kind": "quali", "row": row}, None, cls)
            for row in await self._client.driver_standings(season):
                yield RawItem(Channel.STANDINGS, {"row": row}, None, cls)
        except JolpicaError as exc:
            log.error("jolpica run failed: %s", exc)
            return

    @staticmethod
    def _schedule_payload(race: dict) -> dict:
        circuit = race.get("Circuit") or {}
        location = circuit.get("Location") or {}
        return {
            "session_key": f"{race.get('season')}-r{race.get('round')}",
            "meeting_key": str(race.get("season")),
            "session_type": "Race",
            "session_name": race.get("raceName"),
            "date_start": race.get("date"),
            "date_end": None,
            "circuit_short_name": circuit.get("circuitName"),
            "country_code": None,
            "country_name": location.get("country"),
            "location": location.get("locality"),
            "gmt_offset": race.get("time"),
            "year": int(race.get("season", 0)) or None,
            "is_cancelled": False,
            "meeting_name": race.get("raceName"),
        }
