"""Phase 12A: one session's spatial inputs, read from its recording.

Only laps, pit stops, location samples and the session/driver identity rows
are read. Every row is identity-guarded (fail closed), and location samples
are bucketed by the row's OWN driver number, so one driver's positions can
never be attributed to another. Nothing is repaired: unusable samples are
dropped and counted, never guessed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.ingest.recorder import iter_recording_models

MODEL_TYPES = frozenset({"SessionInfo", "Driver", "Lap", "PitStop", "TelemetryLocationSample"})

# Evidence for the DRS capability, counted without parsing car samples.
DRS_MARKERS: dict[str, tuple[bytes, ...]] = {
    "car_samples": (b'"type":"TelemetryCarSample"',),
    "car_drs_null": (b'"type":"TelemetryCarSample"', b'"drs":null'),
}

Sample = tuple[float, float, float]  # (t epoch seconds UTC, x, y) in feed units


class SpatialIdentityError(ValueError):
    """A row belongs to another session, or its envelope and row disagree on
    the driver. The build fails closed."""


@dataclass(frozen=True)
class LapRow:
    driver: int
    lap: int
    start: float
    duration: float | None
    s1: float | None
    s2: float | None
    pit_out: bool


@dataclass(frozen=True)
class PitRow:
    driver: int
    ts: float
    lap: int | None
    lane_s: float | None


@dataclass(frozen=True)
class SpatialInputs:
    session_id: str
    session: dict
    drivers: tuple[int, ...]
    laps: dict[int, tuple[LapRow, ...]]
    pits: dict[int, tuple[PitRow, ...]]
    samples: dict[int, tuple[Sample, ...]]
    counts: dict[str, int]
    input_digest: str


def _t(value: object) -> float:
    return datetime.fromisoformat(str(value)).timestamp()


def _opt(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _check(session_id: str, meta: dict, model: dict) -> None:
    mtype, seq = model.get("type"), meta.get("seq")
    if meta.get("session_id") != session_id:
        raise SpatialIdentityError(f"{mtype} seq {seq}: envelope session "
                                   f"{meta.get('session_id')!r} is not {session_id!r}")
    row_sid = model.get("session_id")
    if row_sid is not None and row_sid != session_id:
        raise SpatialIdentityError(f"{mtype} seq {seq}: row session {row_sid!r} "
                                   f"is not {session_id!r}")
    env_d, row_d = meta.get("driver_number"), model.get("driver_number")
    if env_d is not None and row_d is not None and int(env_d) != int(row_d):
        raise SpatialIdentityError(f"{mtype} seq {seq}: envelope driver {env_d} "
                                   f"disagrees with row driver {row_d}")


check_row = _check  # the identity guard, shared with the Phase 12C recording store


def _digest(laps: dict[int, tuple[LapRow, ...]], pits: dict[int, tuple[PitRow, ...]],
            samples: dict[int, tuple[Sample, ...]]) -> str:
    payload = {
        "laps": [[r.driver, r.lap, r.start, r.duration, r.s1, r.s2, r.pit_out]
                 for d in sorted(laps) for r in laps[d]],
        "pits": [[p.driver, p.ts, p.lap, p.lane_s] for d in sorted(pits) for p in pits[d]],
        "samples": {str(d): [list(s) for s in samples[d]] for d in sorted(samples)},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def inputs_from_rows(session_id: str, rows: Iterable[tuple[dict, dict]],
                     counts: Mapping[str, int] | None = None) -> SpatialInputs:
    """Identity-guarded, per-driver, time-sorted inputs from (envelope, model) rows."""
    session: dict = {}
    drivers: set[int] = set()
    laps: dict[tuple[int, int], LapRow] = {}
    pits: set[PitRow] = set()
    raw: dict[int, dict[float, list[tuple[float, float]]]] = {}
    tally = {"null_xy": 0, "no_fix": 0, "duplicate_identical": 0,
             "duplicate_conflicting": 0, "lap_duplicates": 0, "lap_no_start": 0}
    for meta, model in rows:
        _check(session_id, meta, model)
        mtype = model.get("type")
        if mtype == "SessionInfo":
            session = {k: v for k, v in model.items() if k not in ("type", "provenance")}
        elif mtype == "Driver":
            if meta.get("driver_number") is not None:
                drivers.add(int(meta["driver_number"]))
        elif mtype == "Lap":
            if model.get("started_at") is None:
                tally["lap_no_start"] += 1
                continue
            key = (int(model["driver_number"]), int(model["lap_number"]))
            if key in laps:
                tally["lap_duplicates"] += 1  # the later row wins, as in the Phase 11 timeline
            laps[key] = LapRow(driver=key[0], lap=key[1], start=_t(model["started_at"]),
                               duration=_opt(model.get("duration_s")),
                               s1=_opt(model.get("sector1_s")), s2=_opt(model.get("sector2_s")),
                               pit_out=bool(model.get("is_pit_out_lap")))
        elif mtype == "PitStop":
            lap = model.get("lap_number")
            pits.add(PitRow(driver=int(model["driver_number"]), ts=_t(model["ts"]),
                            lap=None if lap is None else int(lap),
                            lane_s=_opt(model.get("lane_duration_s"))))
        elif mtype == "TelemetryLocationSample":
            x, y, z = model.get("x"), model.get("y"), model.get("z")
            if x is None or y is None:
                tally["null_xy"] += 1
                continue
            if x == 0 and y == 0 and z == 0:
                tally["no_fix"] += 1  # (0, 0, 0): the feed's no-fix placeholder
                continue
            raw.setdefault(int(model["driver_number"]), {}) \
               .setdefault(_t(model["ts"]), []).append((float(x), float(y)))

    samples: dict[int, tuple[Sample, ...]] = {}
    for d, by_t in raw.items():
        kept: list[Sample] = []
        for t in sorted(by_t):
            pts = by_t[t]
            if len(set(pts)) > 1:  # same instant, different places: no guess
                tally["duplicate_conflicting"] += len(pts)
                continue
            tally["duplicate_identical"] += len(pts) - 1
            kept.append((t, *pts[0]))
        samples[d] = tuple(kept)
    laps_by: dict[int, tuple[LapRow, ...]] = {}
    for (d, _n), r in sorted(laps.items()):
        laps_by[d] = (*laps_by.get(d, ()), r)
    pits_by: dict[int, tuple[PitRow, ...]] = {}
    for p in sorted(pits, key=lambda p: (p.driver, p.ts)):
        pits_by[p.driver] = (*pits_by.get(p.driver, ()), p)
    return SpatialInputs(session_id=session_id, session=session, drivers=tuple(sorted(drivers)),
                         laps=laps_by, pits=pits_by, samples=samples,
                         counts={**dict(counts or {}), **tally},
                         input_digest=_digest(laps_by, pits_by, samples))


def load_inputs(recording_dir: Path, session_id: str) -> SpatialInputs:
    """Read a recording once: spatial rows parsed, car samples only counted."""
    counts: dict[str, int] = {}
    rows = iter_recording_models(Path(recording_dir) / "frames.jsonl.zst", MODEL_TYPES,
                                 DRS_MARKERS, counts)
    return inputs_from_rows(session_id, rows, counts)
