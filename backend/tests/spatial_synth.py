"""Synthetic spatial session for the Phase 12A tests (exact geometry).

Cars run counter-clockwise round a square of side SIDE feed units at constant
speed. Every quantity has a closed form: where a car is at time t, when it
crosses the finish line (mid-edge, so line probes never straddle a corner),
and the sector lines at a third and two thirds of the lap. Synthetic data is
for unit tests only - never evidence that the real pipeline works.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.events import Envelope
from app.ingest.recorder import Recorder

SID = "openf1:1"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SIDE = 1000.0
LENGTH = 4 * SIDE
FINISH_S = SIDE / 2
LAP_S = 60.0
DT = 0.25
PIT_OFFSET = 200.0

Row = tuple[dict, dict]


def track_xy(s: float) -> tuple[float, float]:
    """Point at arc length s: counter-clockwise from (0, 0) along +x."""
    s = s % LENGTH
    if s < SIDE:
        return (s, 0.0)
    if s < 2 * SIDE:
        return (SIDE, s - SIDE)
    if s < 3 * SIDE:
        return (3 * SIDE - s, SIDE)
    return (0.0, LENGTH - s)


@dataclass(frozen=True)
class Car:
    number: int
    start_offset_s: float = 0.0     # first crossing of the finish line, seconds after T0
    lap_s: float = LAP_S
    sample_phase_s: float = 0.0
    last_sample_s: float | None = None  # seconds after T0; None = runs to the end


@dataclass(frozen=True)
class Pit:
    driver: int
    lap: int
    exit_at_s: float                # PitStop.ts, seconds after T0 (EXIT semantics)
    lane_s: float = 20.0


DEFAULT_CARS = (Car(1), Car(2, 2.0, sample_phase_s=0.1), Car(3, 4.0, sample_phase_s=0.2))


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def s_of(car: Car, seconds: float) -> float:
    """Arc length of `car` at `seconds` after T0."""
    return FINISH_S + (seconds - car.start_offset_s) * LENGTH / car.lap_s


def crossing(car: Car, k: int) -> float:
    """Seconds after T0 of the car's k-th finish-line crossing (0 = first)."""
    return car.start_offset_s + k * car.lap_s


def row(mtype: str, model: dict, driver: int | None = None, sid: str = SID) -> Row:
    return ({"session_id": sid, "driver_number": driver}, {"type": mtype, **model})


def location_row(driver: int, t: datetime, x: float | None, y: float | None,
                 z: float | None = 1.0, sid: str = SID) -> Row:
    return row("TelemetryLocationSample", {"session_id": sid, "driver_number": driver,
                                           "ts": t.isoformat(), "x": x, "y": y, "z": z},
               driver, sid)


def lap_row(driver: int, lap: int, start: datetime, duration: float | None,
            s1: float | None = None, s2: float | None = None, pit_out: bool = False,
            sid: str = SID) -> Row:
    third = None if duration is None else duration / 3
    return row("Lap", {"session_id": sid, "driver_number": driver, "lap_number": lap,
                       "started_at": start.isoformat(), "duration_s": duration,
                       "sector1_s": third if s1 is None else s1,
                       "sector2_s": third if s2 is None else s2,
                       "sector3_s": third, "is_pit_out_lap": pit_out, "deleted": False},
               driver, sid)


def pit_row(driver: int, lap: int, ts: datetime, lane_s: float | None, sid: str = SID) -> Row:
    return row("PitStop", {"session_id": sid, "driver_number": driver, "ts": ts.isoformat(),
                           "lap_number": lap, "lane_duration_s": lane_s,
                           "stop_duration_s": None}, driver, sid)


def car_sample_row(driver: int, t: datetime, drs: int | None, sid: str = SID) -> Row:
    return row("TelemetryCarSample", {"session_id": sid, "driver_number": driver,
                                      "ts": t.isoformat(), "speed_kph": 200, "drs": drs},
               driver, sid)


def sample_times(car: Car, laps: int) -> list[float]:
    first = car.start_offset_s - 5.0 + car.sample_phase_s
    end = crossing(car, laps) + 5.0
    if car.last_sample_s is not None:
        end = min(end, car.last_sample_s)
    n = math.floor((end - first) / DT + 1e-9)
    return [first + j * DT for j in range(n + 1)]


def expected_xy(car: Car, seconds: float, pits: tuple[Pit, ...] = ()) -> tuple[float, float]:
    x, y = track_xy(s_of(car, seconds))
    for p in pits:
        if p.driver == car.number and p.exit_at_s - p.lane_s <= seconds <= p.exit_at_s:
            return x, y - PIT_OFFSET
    return x, y


def synth_rows(cars: tuple[Car, ...] = DEFAULT_CARS, laps: int = 6, pits: tuple[Pit, ...] = (),
               circuit: str = "Synthetic", extra: tuple[Row, ...] = ()) -> list[Row]:
    rows: list[Row] = [row("SessionInfo", {"session_id": SID, "provider": "openf1",
                                           "provider_session_key": "1", "session_name": "Race",
                                           "session_type": "Race", "year": 2026,
                                           "circuit_short_name": circuit,
                                           "date_start": T0.isoformat()})]
    for car in cars:
        rows.append(row("Driver", {"driver_id": f"d{car.number}",
                                   "name_acronym": f"D{car.number}"}, car.number))
        rows += [lap_row(car.number, k + 1, at(crossing(car, k)), car.lap_s)
                 for k in range(laps)]
        rows += [location_row(car.number, at(t), *expected_xy(car, t, pits))
                 for t in sample_times(car, laps)]
    rows += [pit_row(p.driver, p.lap, at(p.exit_at_s), p.lane_s) for p in pits]
    return rows + list(extra)


def write_recording(root: Path, rows: list[Row], sid: str = SID,
                    name: str = "openf1-1-race") -> Path:
    rec = Recorder(root, name)
    for meta, model in rows:
        ts = model.get("ts") or model.get("started_at")
        rec.write(Envelope(event_type="x", session_id=meta["session_id"], source="test",
                           driver_number=meta["driver_number"],
                           source_timestamp=datetime.fromisoformat(ts) if ts else None,
                           ingestion_timestamp=T0, provenance_class="B",
                           payload={"model": model}))
    rec.write_meta(session_payload={"session_id": sid, "provider_session_key": sid.split(":")[-1],
                                    "circuit_short_name": "Synthetic"},
                   provider_name="openf1")
    rec.finalize()
    return rec.dir
