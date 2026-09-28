"""Phase 12C: laps and car/location telemetry of a recorded session.

A recording is the replay source of truth. This store serves the same
canonical models the database would (`Lap`, `TelemetryCarSample`, raw
location rows), so the unchanged 10.x evidence engines and the telemetry
route run on a recorded session without Postgres.

Rules (fail closed, nothing repaired):
- every row passes the Phase 12A identity guard (session and driver);
- samples are bucketed by the row's OWN driver number;
- a null stays null: ints are stored with a sentinel and floats as NaN,
  and both read back as None;
- identical duplicates (same driver, same instant, same values) collapse to
  one; conflicting duplicates are all dropped and counted, never chosen;
- lap rows: the later row wins (the Phase 11/12A rule);
- `deleted` is True/False only from a LapCorrection record, else None (the
  recorded `Lap.deleted=False` is a model default, not an observation).

Caches next to the recording, rebuilt (never served) on any mismatch:

    laps_v1.json               session, identities, laps, corrections, counts
    telemetry_v1.bin           per-driver car and location arrays
    recording_store_v1.key     "<store version>|<frames size>|<frames mtime_ns>"
"""

from __future__ import annotations

import json
import math
import struct
import threading
from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Lap, Provenance, TelemetryCarSample
from app.evidence.lap_comparison import SourceInfo
from app.ingest.recorder import iter_recording_models
from app.spatial.source import check_row
from app.storage.timeline_store import index_recordings

STORE_VERSION = "recording-store-1.0.0"
LAPS_NAME = "laps_v1.json"
BIN_NAME = "telemetry_v1.bin"
KEY_NAME = "recording_store_v1.key"
MODEL_TYPES = frozenset({"SessionInfo", "Driver", "Lap", "LapCorrection",
                         "TelemetryCarSample", "TelemetryLocationSample"})

_MAGIC = b"LFIRS1\x00\x00"
_INT_NULL = -(2 ** 31)
_BYTE_NULL = -128
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_US = timedelta(microseconds=1)
# (field, typecode) in file order. Classes are the provenance letter's code point, 0 = none.
_CAR = (("t", "q"), ("rpm", "i"), ("speed_kph", "i"), ("gear", "b"), ("throttle_pct", "d"),
        ("brake_pct", "d"), ("drs", "i"), ("cls", "b"))
_LOC = (("t", "q"), ("x", "d"), ("y", "d"), ("z", "d"), ("cls", "b"))
_CAR_VALUES = ("rpm", "speed_kph", "gear", "throttle_pct", "brake_pct", "drs")


class RecordingStoreError(ValueError):
    """A cache file is unreadable or disagrees with its recording (rebuild)."""


def _us(value: datetime | str) -> int:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return (dt - _EPOCH) // _US


def _dt(us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


def _enc(code: str, v: Any) -> Any:
    if code == "d":
        return math.nan if v is None else float(v)
    if v is None:
        return _BYTE_NULL if code == "b" else _INT_NULL
    return int(v)


def _dec(code: str, v: Any) -> Any:
    if code == "d":
        return None if math.isnan(v) else v  # NaN is the stored null
    return None if v == (_BYTE_NULL if code == "b" else _INT_NULL) else v


def _cls(model: dict) -> int:
    letter = (model.get("provenance") or {}).get("provenance_class")
    return ord(letter) if letter else 0


def _dedupe(rows: list[tuple[int, tuple, int]], tally: dict[str, int], prefix: str) -> list:
    """Sort by time; keep one of identical duplicates, drop every conflicting one."""
    rows.sort(key=lambda r: r[0])
    kept: list[tuple[int, tuple, int]] = []
    i = 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and rows[j][0] == rows[i][0]:
            j += 1
        group = rows[i:j]
        if len({g[1] for g in group}) > 1:  # same instant, different values: no guess
            tally[f"{prefix}_duplicate_conflicting"] += len(group)
        else:
            tally[f"{prefix}_duplicate_identical"] += len(group) - 1
            kept.append(group[0])
        i = j
    return kept


def _columns(rows: list[tuple[int, tuple, int]], layout: tuple) -> list[array]:
    cols = [array(code) for _name, code in layout]
    for t, values, cls in rows:
        cols[0].append(t)
        for k, v in enumerate(values, start=1):
            cols[k].append(_enc(layout[k][1], v))
        cols[-1].append(cls)
    return cols


@dataclass
class _Session:
    doc: dict                          # laps_v1.json content
    car: dict[int, list[array]]
    loc: dict[int, list[array]]


def _build(rec: Path, session_id: str, key: str) -> _Session:
    tally = {"car_rows": 0, "location_rows": 0, "car_duplicate_identical": 0,
             "car_duplicate_conflicting": 0, "location_duplicate_identical": 0,
             "location_duplicate_conflicting": 0, "lap_duplicates": 0, "lap_no_start": 0,
             "corrections": 0}
    session: dict | None = None
    idents: dict[int, dict] = {}
    laps: dict[tuple[int, int], dict] = {}
    corrections: dict[tuple[int, int], str] = {}
    car_raw: dict[int, list] = {}
    loc_raw: dict[int, list] = {}
    for meta, model in iter_recording_models(rec / "frames.jsonl.zst", MODEL_TYPES):
        check_row(session_id, meta, model)
        mtype = model.get("type")
        if mtype == "TelemetryCarSample":
            tally["car_rows"] += 1
            car_raw.setdefault(int(model["driver_number"]), []).append(
                (_us(model["ts"]), tuple(model.get(k) for k in _CAR_VALUES), _cls(model)))
        elif mtype == "TelemetryLocationSample":
            tally["location_rows"] += 1
            loc_raw.setdefault(int(model["driver_number"]), []).append(
                (_us(model["ts"]), (model.get("x"), model.get("y"), model.get("z")),
                 _cls(model)))
        elif mtype == "Lap":
            if model.get("started_at") is None:
                tally["lap_no_start"] += 1
                continue
            lk = (int(model["driver_number"]), int(model["lap_number"]))
            if lk in laps:
                tally["lap_duplicates"] += 1  # the later row wins
            laps[lk] = {k: v for k, v in model.items() if k != "type"}
        elif mtype == "LapCorrection":
            tally["corrections"] += 1
            corrections[(int(model["driver_number"]), int(model["lap_number"]))] = \
                str(model.get("kind"))
        elif mtype == "Driver":
            if meta.get("driver_number") is not None:
                team = model.get("team") or {}
                idents[int(meta["driver_number"])] = {
                    "acronym": model.get("name_acronym"), "full_name": model.get("full_name"),
                    "team_name": team.get("display_name"), "team_colour": team.get("colour_hex")}
        elif mtype == "SessionInfo":
            session = {k: v for k, v in model.items() if k not in ("type", "provenance")}

    car = {d: _columns(_dedupe(rows, tally, "car"), _CAR) for d, rows in car_raw.items()}
    loc = {d: _columns(_dedupe(rows, tally, "location"), _LOC)
           for d, rows in loc_raw.items()}
    lap_rows = []
    for (d, n), model in sorted(laps.items()):
        kind = corrections.get((d, n))
        deleted = True if kind == "LAP_DELETED" else False if kind == "LAP_REINSTATED" else None
        has_car = False
        if model.get("duration_s") is not None and d in car:
            start = _us(model["started_at"])
            end = start + round(float(model["duration_s"]) * 1_000_000)
            ts = car[d][0]
            i = bisect_left(ts, start)
            has_car = i < len(ts) and ts[i] <= end
        lap_rows.append({"driver_number": d, "lap_number": n, "deleted": deleted,
                         "has_car_telemetry": has_car, "model": model})
    doc = {"key": key, "session_id": session_id, "session": session,
           "drivers": {str(d): v for d, v in sorted(idents.items())},
           "laps": lap_rows, "counts": tally}
    return _Session(doc=doc, car=car, loc=loc)


def _write(rec: Path, data: _Session, key: str) -> None:
    header = json.dumps({"key": key,
                         "car": {str(d): len(c[0]) for d, c in sorted(data.car.items())},
                         "loc": {str(d): len(c[0]) for d, c in sorted(data.loc.items())}},
                        separators=(",", ":")).encode()
    parts = [_MAGIC, struct.pack("<Q", len(header)), header]
    for store in (data.car, data.loc):
        for d in sorted(store):
            parts += [col.tobytes() for col in store[d]]
    (rec / LAPS_NAME).write_text(json.dumps(data.doc, separators=(",", ":")), encoding="utf-8")
    (rec / BIN_NAME).write_bytes(b"".join(parts))
    (rec / KEY_NAME).write_text(key, encoding="utf-8")  # last: marks both caches complete


def _read(rec: Path, session_id: str, key: str) -> _Session:
    doc = json.loads((rec / LAPS_NAME).read_text(encoding="utf-8"))
    if doc.get("key") != key or doc.get("session_id") != session_id:
        raise RecordingStoreError("laps cache belongs to another build or session")
    raw = (rec / BIN_NAME).read_bytes()
    if raw[:8] != _MAGIC:
        raise RecordingStoreError("telemetry cache has no magic")
    (hlen,) = struct.unpack("<Q", raw[8:16])
    header = json.loads(raw[16:16 + hlen])
    if header.get("key") != key:
        raise RecordingStoreError("telemetry cache belongs to another build")
    pos = 16 + hlen
    out: list[dict[int, list[array]]] = []
    for part, layout in (("car", _CAR), ("loc", _LOC)):
        store: dict[int, list[array]] = {}
        for d, n in sorted(header[part].items(), key=lambda kv: int(kv[0])):
            cols = []
            for _name, code in layout:
                col = array(code)
                size = n * col.itemsize
                if pos + size > len(raw):
                    raise RecordingStoreError("telemetry cache truncated")
                col.frombytes(raw[pos:pos + size])
                pos += size
                cols.append(col)
            store[int(d)] = cols
        out.append(store)
    if pos != len(raw):
        raise RecordingStoreError("telemetry cache has trailing bytes")
    return _Session(doc=doc, car=out[0], loc=out[1])


class RecordingStore:
    def __init__(self, recordings_dir: Path) -> None:
        self.root = Path(recordings_dir)
        self._memory: dict[str, tuple[str, _Session]] = {}
        self._lock = threading.Lock()

    def recording_for(self, session_id: str) -> Path | None:
        return index_recordings(self.root).get(session_id)

    def _session(self, session_id: str) -> _Session:
        rec = self.recording_for(session_id)
        if rec is None:
            raise LookupError(f"no recording holds session {session_id}")
        st = (rec / "frames.jsonl.zst").stat()
        key = f"{STORE_VERSION}|{st.st_size}|{st.st_mtime_ns}"
        with self._lock:
            hit = self._memory.get(session_id)
            if hit and hit[0] == key:
                return hit[1]
            data = None
            key_file = rec / KEY_NAME
            if key_file.exists() and key_file.read_text(encoding="utf-8").strip() == key:
                try:
                    data = _read(rec, session_id, key)
                except (OSError, ValueError, KeyError, struct.error):
                    data = None  # unreadable cache: rebuilt below, never served
            if data is None:
                data = _build(rec, session_id, key)
                _write(rec, data, key)
            self._memory[session_id] = (key, data)
            return data

    # ------------------------------------------------------------ session

    def session_source(self, session_id: str) -> SourceInfo:
        s = self._session(session_id).doc.get("session") or {}
        return SourceInfo(session_id=session_id, provider=s.get("provider"),
                          session_type=s.get("session_type"), season=s.get("year"),
                          event=s.get("meeting_name"), circuit=s.get("circuit_short_name"))

    def counts(self, session_id: str) -> dict[str, int]:
        return dict(self._session(session_id).doc["counts"])

    @staticmethod
    def _provider(data: _Session) -> ProviderName:
        return ProviderName((data.doc.get("session") or {}).get("provider") or "openf1")

    # --------------------------------------------------------------- laps

    def lap(self, session_id: str, driver: int, lap: int) -> Lap:
        data = self._session(session_id)
        for entry in data.doc["laps"]:
            if entry["driver_number"] == driver and entry["lap_number"] == lap:
                return Lap.model_validate({**entry["model"],
                                           "deleted": entry["deleted"] is True})
        raise LookupError(f"lap {lap} unknown for driver {driver}")

    def lap_catalog(self, session_id: str) -> dict:
        """The shape of Repository.session_lap_catalog, from the recording."""
        data = self._session(session_id)
        drivers: dict[int, dict] = {
            int(d): {"driver_number": int(d), **ident, "laps": []}
            for d, ident in data.doc["drivers"].items()}
        for entry in data.doc["laps"]:
            d, model = entry["driver_number"], entry["model"]
            drivers.setdefault(d, {"driver_number": d, "acronym": None, "full_name": None,
                                   "team_name": None, "team_colour": None, "laps": []})
            drivers[d]["laps"].append({
                "lap_number": entry["lap_number"],
                "started_at": datetime.fromisoformat(model["started_at"]),
                "duration_s": model.get("duration_s"), "deleted": entry["deleted"],
                "is_pit_out_lap": model.get("is_pit_out_lap"),
                "has_car_telemetry": entry["has_car_telemetry"]})
        return {"session_id": session_id, "drivers": [drivers[k] for k in sorted(drivers)]}

    # ---------------------------------------------------------- telemetry

    @staticmethod
    def _slice(cols: list[array] | None, t0: datetime, t1: datetime) -> range:
        if not cols:
            return range(0)
        ts = cols[0]
        return range(bisect_left(ts, _us(t0)), bisect_right(ts, _us(t1)))

    def car_rows(self, session_id: str, driver: int, t0: datetime, t1: datetime) -> list[dict]:
        """Car samples in [t0, t1] shaped like the telemetry_car table's rows."""
        cols = self._session(session_id).car.get(driver)
        out = []
        for i in self._slice(cols, t0, t1):
            r: dict[str, Any] = {"ts": _dt(cols[0][i])}
            for k, (name, code) in enumerate(_CAR[1:-1], start=1):
                r[name] = _dec(code, cols[k][i])
            r["provenance_class"] = chr(cols[-1][i]) if cols[-1][i] else None
            out.append(r)
        return out

    def car_samples(self, session_id: str, driver: int, t0: datetime,
                    t1: datetime) -> list[TelemetryCarSample]:
        provider = self._provider(self._session(session_id))
        return [TelemetryCarSample(
            session_id=session_id, driver_number=driver, ts=r["ts"], rpm=r["rpm"],
            speed_kph=r["speed_kph"], gear=r["gear"], throttle_pct=r["throttle_pct"],
            brake_pct=r["brake_pct"], drs=r["drs"],
            provenance=Provenance(provider=provider,
                                  provenance_class=ProvenanceClass(r["provenance_class"] or "B")))
            for r in self.car_rows(session_id, driver, t0, t1)]

    def location_rows(self, session_id: str, driver: int, t0: datetime,
                      t1: datetime) -> list[dict]:
        """Raw location samples in [t0, t1] shaped like telemetry_location rows."""
        cols = self._session(session_id).loc.get(driver)
        return [{"ts": _dt(cols[0][i]), "x": _dec("d", cols[1][i]), "y": _dec("d", cols[2][i]),
                 "z": _dec("d", cols[3][i]),
                 "provenance_class": chr(cols[-1][i]) if cols[-1][i] else None}
                for i in self._slice(cols, t0, t1)]
