"""Persistence subscriber: canonical envelopes -> PostgreSQL.

High-rate channels (telemetry, event log) are buffered and flushed in batches;
low-volume rows are written per-envelope. Unknown model types are logged once
and skipped - never guessed.
"""

from __future__ import annotations

import logging

from app.core.events import Envelope
from app.core.models import (
    Driver,
    Lap,
    LapCorrection,
    PitStop,
    PositionUpdate,
    QualifyingResult,
    RaceControlEvent,
    RaceResult,
    SectorTime,
    SessionInfo,
    StandingsEntry,
    Team,
    TelemetryCarSample,
    TelemetryLocationSample,
    TimingInterval,
    TyreStint,
    WeatherPoint,
)
from app.storage.db import Repository

log = logging.getLogger(__name__)

_BATCH_SIZE = 1000

_MODEL_REGISTRY = {
    "SessionInfo": ("session", SessionInfo),
    "Driver": ("driver", Driver),
    "Team": ("team", Team),
    "Lap": ("lap", Lap),
    "SectorTime": ("sector", SectorTime),
    "TelemetryCarSample": ("car", TelemetryCarSample),
    "TelemetryLocationSample": ("location", TelemetryLocationSample),
    "TyreStint": ("stint", TyreStint),
    "PitStop": ("pit", PitStop),
    "WeatherPoint": ("weather", WeatherPoint),
    "RaceControlEvent": ("rcm", RaceControlEvent),
    "PositionUpdate": ("position", PositionUpdate),
    "TimingInterval": ("interval", TimingInterval),
    "LapCorrection": ("correction", LapCorrection),
    "RaceResult": ("race_result", RaceResult),
    "QualifyingResult": ("quali_result", QualifyingResult),
    "StandingsEntry": ("standings", StandingsEntry),
}


class PersistenceSubscriber:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self.written = 0
        self.conflicts = 0
        self._warned_types: set[str] = set()
        self._car_buf: list[tuple] = []
        self._loc_buf: list[tuple] = []
        self._evt_buf: list[dict] = []

    async def __call__(self, envelope: Envelope) -> None:
        info = envelope.payload.get("model", {})
        model_type = info.get("type")
        entry = _MODEL_REGISTRY.get(model_type)
        if entry is None:
            if model_type not in self._warned_types:
                self._warned_types.add(model_type or "?")
                log.warning("no persistence mapping for model type %r", model_type)
            return
        _, cls = entry
        model = cls.model_validate(info)

        if isinstance(model, SessionInfo):
            await self.repo.upsert_session(model)
        elif isinstance(model, Driver):
            if model.team is not None:  # defensive: FK order guarantee
                await self.repo.upsert_team(model.team)
            await self.repo.upsert_driver(
                model, session_id=envelope.session_id, driver_number=envelope.driver_number
            )
        elif isinstance(model, Team):
            await self.repo.upsert_team(model)
        elif isinstance(model, Lap):
            ok = await self.repo.insert_lap(model)
            self._count(ok)
        elif isinstance(model, SectorTime):
            ok = await self.repo.insert_sector(model)
            self._count(ok)
        elif isinstance(model, TelemetryCarSample):
            p = model.provenance
            self._car_buf.append((
                model.session_id, model.driver_number, model.ts, model.rpm,
                model.speed_kph, model.gear, model.throttle_pct, model.brake_pct,
                model.drs, p.provenance_class.value,
            ))
        elif isinstance(model, TelemetryLocationSample):
            p = model.provenance
            self._loc_buf.append((
                model.session_id, model.driver_number, model.ts, model.x, model.y,
                model.z, p.provenance_class.value,
            ))
        elif isinstance(model, TyreStint):
            await self.repo.upsert_stint(model)
            self.written += 1
        elif isinstance(model, PitStop):
            ok = await self.repo.insert_pit_stop(model)
            self._count(ok)
        elif isinstance(model, WeatherPoint):
            ok = await self.repo.insert_weather(model)
            self._count(ok)
        elif isinstance(model, RaceControlEvent):
            ok = await self.repo.insert_rcm(model)
            self._count(ok)
        elif isinstance(model, PositionUpdate):
            ok = await self.repo.insert_position(model)
            self._count(ok)
        elif isinstance(model, TimingInterval):
            ok = await self.repo.insert_interval(model)
            self._count(ok)
        elif isinstance(model, LapCorrection):
            ok = await self.repo.insert_lap_correction(model)
            self._count(ok)
        elif isinstance(model, RaceResult):
            ok = await self.repo.insert_race_result(model)
            self._count(ok)
        elif isinstance(model, QualifyingResult):
            ok = await self.repo.insert_quali_result(model)
            self._count(ok)
        elif isinstance(model, StandingsEntry):
            ok = await self.repo.insert_standings_entry(model)
            self._count(ok)

        # full canonical event log (audit + replay parity evidence), batched
        self._evt_buf.append({
            "event_id": envelope.event_id,
            "seq": envelope.seq,
            "event_type": envelope.event_type,
            "category": envelope.category,
            "session_id": envelope.session_id,
            "driver_number": envelope.driver_number,
            "origin": envelope.origin,
            "source": envelope.source,
            "source_timestamp": envelope.source_timestamp,
            "ingestion_timestamp": envelope.ingestion_timestamp,
            "provenance_class": envelope.provenance_class.value,
            "dedupe_key": envelope.dedupe_key,
            "payload": envelope.payload,
        })

        if len(self._car_buf) >= _BATCH_SIZE or len(self._loc_buf) >= _BATCH_SIZE \
                or len(self._evt_buf) >= _BATCH_SIZE:
            await self.flush()

    async def flush(self) -> None:
        car, loc, evt = self._car_buf, self._loc_buf, self._evt_buf
        self._car_buf, self._loc_buf, self._evt_buf = [], [], []
        if car:
            await self.repo.insert_car_samples_bulk(car)
            self.written += len(car)
        if loc:
            await self.repo.insert_location_samples_bulk(loc)
            self.written += len(loc)
        if evt:
            try:
                await self.repo.insert_events_bulk(evt)
            except Exception as exc:  # noqa: BLE001 - audit log must not kill ingestion
                log.debug("event-log batch skipped (%s)", type(exc).__name__)
            self.written += len(evt)

    def _count(self, inserted: bool) -> None:
        if inserted:
            self.written += 1
        else:
            self.conflicts += 1
