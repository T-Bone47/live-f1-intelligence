"""Channel dispatch: raw vendor items -> canonical Envelopes.

This is the ONLY place provider payloads become canonical models. A payload
keyed "__envelope" (replay) bypasses vendor mapping entirely - recorded
envelopes are already canonical.
"""

from __future__ import annotations

from app.core.enums import ProvenanceClass
from app.core.events import Envelope, make_envelope
from app.core.models import (
    Driver,
    Lap,
    PitStop,
    PositionUpdate,
    RaceControlEvent,
    SectorTime,
    SessionInfo,
    TelemetryCarSample,
    TelemetryLocationSample,
    TimingInterval,
    TyreStint,
    WeatherPoint,
)
from app.providers.base import Channel, RawItem
from app.providers.openf1 import mapping as om

EVENT_TYPES = {
    "session.discovered",
    "driver.detected",
    "team.detected",
    "lap.completed",
    "sector.recorded",
    "telemetry.car_sample",
    "telemetry.location_sample",
    "tyre.stint_recorded",
    "pit.recorded",
    "weather.updated",
    "rcm.message",
    "lap.deleted",
    "lap.reinstated",
    "position.changed",
    "timing.interval_updated",
    "result.race_loaded",
    "result.quali_loaded",
    "standings.entry",
}


def normalize(item: RawItem, session_id: str, ingestion_ts) -> list[Envelope]:
    """Convert one RawItem into 0..N canonical envelopes.

    Raises NormalizationError for malformed records - the pipeline counts and
    continues (never crashes, never fabricates).
    """
    if "__envelope" in item.payload:  # replay passthrough
        env = Envelope.model_validate(item.payload["__envelope"])
        return [env.model_copy(update={"origin": "replay"})]

    prov_cls = item.provenance_class or ProvenanceClass.B
    out: list[Envelope] = []

    if item.channel is Channel.SESSION_META:
        model = om.safe(om.to_session, item.payload, prov_cls)
        out.append(
            make_envelope(
                event_type="session.discovered",
                session_id=model.session_id,
                model=model,
                source="openf1",
                dedupe_key=f"session:{model.provider}:{model.provider_session_key}",
            )
        )
    elif item.channel is Channel.DRIVER_LIST:
        driver: Driver = om.safe(om.to_driver, item.payload, prov_cls)
        # teams first: drivers table carries a FK to teams
        if driver.team is not None:
            out.append(
                make_envelope(
                    event_type="team.detected",
                    session_id=session_id,
                    model=driver.team,
                    source="openf1",
                    dedupe_key=f"team:{driver.team.team_id}",
                )
            )
        out.append(
            make_envelope(
                event_type="driver.detected",
                session_id=session_id,
                model=driver,
                source="openf1",
                dedupe_key=f"driver:{driver.driver_id}",
                driver_number=int(item.payload["driver_number"]),
            )
        )
    elif item.channel is Channel.LAP:
        lap: Lap
        sectors: list[SectorTime]
        lap, sectors = om.safe(om.to_lap, item.payload, session_id, prov_cls)
        out.append(
            make_envelope(
                event_type="lap.completed",
                session_id=session_id,
                model=lap,
                source="openf1",
                dedupe_key=f"lap:{lap.session_id}:{lap.driver_number}:{lap.lap_number}",
            )
        )
        for sec in sectors:
            out.append(
                make_envelope(
                    event_type="sector.recorded",
                    session_id=session_id,
                    model=sec,
                    source="openf1",
                    dedupe_key=(
                        f"sector:{sec.session_id}:{sec.driver_number}:"
                        f"{sec.lap_number}:{sec.sector_index}"
                    ),
                )
            )
    elif item.channel is Channel.CAR_DATA:
        sample = om.safe(om.to_car_sample, item.payload, session_id, prov_cls)
        out.append(_sample_env("telemetry.car_sample", sample))
    elif item.channel is Channel.LOCATION:
        sample = om.safe(om.to_location_sample, item.payload, session_id, prov_cls)
        out.append(_sample_env("telemetry.location_sample", sample))
    elif item.channel is Channel.STINT:
        stint = om.safe(om.to_stint, item.payload, session_id, prov_cls)
        out.append(
            make_envelope(
                event_type="tyre.stint_recorded",
                session_id=session_id,
                model=stint,
                source="openf1",
                dedupe_key=(
                    f"stint:{stint.session_id}:{stint.driver_number}:{stint.stint_number}"
                ),
            )
        )
    elif item.channel is Channel.PIT:
        pit = om.safe(om.to_pit_stop, item.payload, session_id, prov_cls)
        out.append(
            make_envelope(
                event_type="pit.recorded",
                session_id=session_id,
                model=pit,
                source="openf1",
                dedupe_key=f"pit:{pit.session_id}:{pit.driver_number}:{pit.ts.isoformat()}",
            )
        )
    elif item.channel is Channel.WEATHER:
        wx = om.safe(om.to_weather, item.payload, session_id, prov_cls)
        out.append(
            make_envelope(
                event_type="weather.updated",
                session_id=session_id,
                model=wx,
                source="openf1",
                dedupe_key=f"wx:{wx.session_id}:{wx.ts.isoformat()}",
            )
        )
    elif item.channel is Channel.RACE_CONTROL:
        rcm: RaceControlEvent = om.safe(om.to_rcm, item.payload, session_id, prov_cls)
        out.append(
            make_envelope(
                event_type="rcm.message",
                session_id=session_id,
                model=rcm,
                source="openf1",
                dedupe_key=f"rcm:{rcm.rcm_key}",
            )
        )
        # lap tombstones derived FROM the message (explicit correction events;
        # history is never silently overwritten)
        from app.ingest.corrections import build_correction

        correction = build_correction(rcm.message, session_id, rcm.rcm_key, rcm.ts, prov_cls)
        if correction is not None:
            kind = "lap.deleted" if correction.kind.value == "LAP_DELETED" else "lap.reinstated"
            out.append(
                make_envelope(
                    event_type=kind,
                    session_id=session_id,
                    model=correction,
                    source="openf1",
                    dedupe_key=(
                        f"corr:{correction.session_id}:{correction.driver_number}:"
                        f"{correction.lap_number}:{correction.kind.value}:{rcm.rcm_key}"
                    ),
                    driver_number=correction.driver_number,
                )
            )
    elif item.channel is Channel.POSITION:
        pos = om.safe(om.to_position, item.payload, session_id, prov_cls)
        out.append(
            make_envelope(
                event_type="position.changed",
                session_id=session_id,
                model=pos,
                source="openf1",
                dedupe_key=(
                    f"pos:{pos.session_id}:{pos.driver_number}:{pos.ts.isoformat()}"
                ),
            )
        )
    elif item.channel is Channel.INTERVALS:
        iv = om.safe(om.to_interval, item.payload, session_id, prov_cls)
        out.append(
            make_envelope(
                event_type="timing.interval_updated",
                session_id=session_id,
                model=iv,
                source="openf1",
                dedupe_key=(
                    f"iv:{iv.session_id}:{iv.driver_number}:{iv.ts.isoformat()}"
                ),
            )
        )
    elif item.channel is Channel.RESULTS:
        from app.providers.jolpica.mapping import quali_row_to_result, result_row_to_race_result

        kind = item.payload.get("kind")
        row = item.payload.get("row", {})
        if kind == "race":
            model = result_row_to_race_result(row, session_id)
            event_type = "result.race_loaded"
        elif kind == "quali":
            model = quali_row_to_result(row, session_id)
            event_type = "result.quali_loaded"
        else:
            raise NormalizationError(f"unknown results kind {kind!r}")
        out.append(
            make_envelope(
                event_type=event_type,
                session_id=session_id,
                model=model,
                source="jolpica",
                dedupe_key=f"{event_type}:{session_id}:{model.driver_ref}",
            )
        )
    elif item.channel is Channel.STANDINGS:
        from app.providers.jolpica.mapping import standing_row_to_entry

        season = int(item.payload.get("season", 0) or 0)
        model = standing_row_to_entry(item.payload.get("row", {}), season)
        out.append(
            make_envelope(
                event_type="standings.entry",
                session_id=session_id,
                model=model,
                source="jolpica",
                dedupe_key=(
                    f"standings:{model.season}:{model.round_after}:{model.driver_ref}"
                ),
            )
        )
    else:
        # Unknown channels are logged upstream; nothing fabricated here.
        raise NormalizationError(f"unhandled channel {item.channel!r}")

    for env in out:
        env.ingestion_timestamp = ingestion_ts
        env.source = _source_for_channel(item.channel)
    return out


def _source_for_channel(channel: Channel) -> str:
    if channel in (Channel.RESULTS, Channel.STANDINGS, Channel.SCHEDULE):
        return "jolpica"
    return "openf1"


def _sample_env(event_type: str, sample) -> Envelope:  # noqa: ANN001
    ts_iso = sample.ts.isoformat()
    kind = "car" if event_type == "telemetry.car_sample" else "loc"
    return make_envelope(
        event_type=event_type,
        session_id=sample.session_id,
        model=sample,
        source="openf1",
        dedupe_key=f"{kind}:{sample.session_id}:{sample.driver_number}:{ts_iso}",
    )


__all__ = ["normalize", "EVENT_TYPES"]
