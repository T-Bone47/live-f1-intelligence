"""Session lap timeline (Phase 11): one authoritative session state per lap.

The Race Command Center shows every panel at ONE session moment. This module
produces those moments by folding canonical envelopes, in race order, through
the same AnalysisEngine the realtime hub uses, and capturing the engine's
snapshot at lap boundaries. Nothing here re-implements an engine: the rows are
the engine's leaderboard, the battles are BattleDetector's, the phase is
RaceControlState's.

    recording (canonical envelopes) -> order_for_replay -> AnalysisEngine
        -> START + one frame per leader lap + FINAL -> session_timeline_v1

Why re-order. A historical OpenF1 backfill records channels in fetch order
(every lap first, then telemetry windows, then pits / weather / race control /
positions / intervals, and stints without timestamps). Folding that order gives
a correct final state but meaningless intermediate states. Effective race-time
rules (deterministic; ties keep recording order):

  Lap         started_at + duration_s (its completion); started_at if no duration
  SectorTime  its lap's completion (else its lap start, else envelope time)
  TyreStint   lap_start <= 1 (the starting tyre) -> before the start; else the
              start of the driver's lap `lap_start`; else completion of lap
              lap_start-1 (the driver's, then the leader's). Anything else is
              UNPLACED and folded last.
  identity    session, team and driver -> before everything
  others      envelope source_timestamp (none -> before everything)

Frames:
  START  state at the earliest lap-1 start time (lights out as timed by lap 1)
  LAP k  state right after the first car (the leader) completes lap k; every
         other car is still on its own lap
  FINAL  state after the last recorded event (offline builds only)

The same TimelineRecorder runs inside the realtime hub (live capture), where
envelopes already arrive in race order; there it captures LAP frames only.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from app.analysis import AnalysisEngine
from app.analysis.common.models import CALC_VERSION
from app.core.events import Envelope

CONTRACT_VERSION = "session_timeline_v1"
BUILDER_VERSION = "timeline-builder-1.0.1"

# The engine does nothing with car/location samples (on_car_sample returns [],
# location has no handler), so skipping them cannot change any frame.
SKIPPED_MODEL_TYPES = frozenset({"TelemetryCarSample", "TelemetryLocationSample"})

# Derived intelligence events kept on the timeline (class C, deduplicated by
# the event engine). Per-lap PB and sector chatter is left out on purpose.
TIMELINE_EVENT_TYPES = frozenset({
    "FASTEST_LAP_CHANGE", "OVERTAKE", "POSITION_CHANGE", "PIT_STOP",
    "SAFETY_CAR", "VSC", "RED_FLAG", "SESSION_STATE_CHANGE",
    "RAIN_START", "RAIN_STOP",
})

_BEFORE_START, _TIMED, _UNPLACED = 0, 1, 2
# session / team / driver identity is context for everything else: always first
IDENTITY_TYPES = frozenset({"SessionInfo", "Team", "Driver"})


def _model(env: Envelope) -> dict:
    return env.payload.get("model", {}) or {}


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# --------------------------------------------------------------- ordering --

def _lap_times(envs: list[Envelope]) -> tuple[dict, dict, dict]:
    starts: dict[tuple[int, int], datetime] = {}
    done: dict[tuple[int, int], datetime] = {}
    for env in envs:
        m = _model(env)
        if m.get("type") != "Lap":
            continue
        key = (int(m["driver_number"]), int(m["lap_number"]))
        start = _dt(m.get("started_at"))
        if start is None:
            continue
        starts[key] = start
        if m.get("duration_s") is not None:
            done[key] = start + timedelta(seconds=float(m["duration_s"]))
    leader_done: dict[int, datetime] = {}
    for (_d, n), t in done.items():
        if n not in leader_done or t < leader_done[n]:
            leader_done[n] = t
    return starts, done, leader_done


def race_start_time(envs: list[Envelope]) -> datetime | None:
    """Earliest lap-1 start: the START frame's moment. None without lap 1."""
    starts, _done, _leader = _lap_times(envs)
    firsts = [t for (_d, n), t in starts.items() if n == 1]
    return min(firsts) if firsts else None


def order_for_replay(envs: list[Envelope]) -> tuple[list[tuple[datetime | None, Envelope]], int]:
    """Envelopes in race order with their effective time.

    Returns (ordered [(effective_time | None, envelope)], unplaced_stint_count).
    Effective time None means "before the start" (identity/metadata) or, for
    unplaced stints, "after everything" - both sorted deterministically.
    """
    starts, done, leader_done = _lap_times(envs)
    keyed: list[tuple[tuple, datetime | None, Envelope]] = []
    unplaced = 0
    for idx, env in enumerate(envs):
        m = _model(env)
        mtype = m.get("type")
        rank, at = _TIMED, None
        if mtype in IDENTITY_TYPES:
            rank = _BEFORE_START
        elif mtype in ("Lap", "SectorTime"):
            key = (int(m["driver_number"]), int(m["lap_number"]))
            at = done.get(key) or starts.get(key) or env.source_timestamp
        elif mtype == "TyreStint":
            d = int(m["driver_number"])
            ls = m.get("lap_start")
            if ls is None or int(ls) <= 1:
                # the starting tyre. Not placed at the lap-1 row: a car that
                # stopped on lap 1 can carry a lap-1 start stamped at a later
                # restart (verified: #3, 2026 Dutch GP red flag)
                rank = _BEFORE_START
            elif (d, int(ls)) in starts:
                at = starts[(d, int(ls))]
            elif (d, int(ls) - 1) in done:
                at = done[(d, int(ls) - 1)]
            elif (int(ls) - 1) in leader_done:
                at = leader_done[int(ls) - 1]
            else:
                rank = _UNPLACED
                unplaced += 1
        else:
            at = env.source_timestamp
        if rank == _TIMED and at is None:
            rank = _BEFORE_START
        sort_key = (rank, at, idx) if rank == _TIMED else (rank, idx)
        keyed.append((sort_key, at if rank == _TIMED else None, env))
    keyed.sort(key=lambda k: k[0])
    return [(at, env) for _k, at, env in keyed], unplaced


# --------------------------------------------------------------- recorder --

class TimelineRecorder:
    """Folds envelopes through an AnalysisEngine and captures session frames.

    Call fold() for every envelope in race order. A LAP frame is captured right
    after the first completion of a new lap number (the leader's). capture()
    can be called directly for START and FINAL.
    """

    def __init__(self, engine: AnalysisEngine, *, fold_into_engine: bool = True) -> None:
        self.engine = engine
        self.fold_into_engine = fold_into_engine
        self.frames: list[dict] = []
        self.last_lap_frame = 0
        self._prev_positions: dict[int, int | None] = {}
        self._pit_counts: dict[int, int] = {}
        self._stints: dict[tuple[int, int], dict] = {}
        self._pits: list[dict] = []
        self._rcm: list[dict] = []
        self._weather: list[dict] = []
        self._events: list[dict] = []
        self._event_keys: set[str] = set()
        self._drivers: dict[int, dict] = {}
        self.session: dict | None = None
        self.folded = 0
        self._digest = hashlib.sha256()
        engine.sig.listeners.append(self._on_event)

    # ----------------------------------------------------------------- fold --

    def fold(self, env: Envelope, at: datetime | None = None) -> None:
        """Fold one envelope (unless the owner already did) and record it."""
        m = _model(env)
        mtype = m.get("type")
        if mtype in SKIPPED_MODEL_TYPES:
            return
        if self.fold_into_engine:
            self.engine.process_envelope(env)
        self.folded += 1
        self._digest.update(json.dumps(
            [_iso(env.source_timestamp), m], sort_keys=True, separators=(",", ":"),
            default=str).encode("utf-8"))
        self._observe(mtype, m, env)
        if mtype == "Lap" and m.get("duration_s") is not None:
            n = int(m["lap_number"])
            if n > self.last_lap_frame:
                start = _dt(m.get("started_at"))
                completed = (start + timedelta(seconds=float(m["duration_s"]))
                             if start else at)
                self.capture("LAP", n, completed)

    def _observe(self, mtype: str | None, m: dict, env: Envelope) -> None:
        pending = len(self.frames)   # index of the first frame that includes this fact
        if mtype == "SessionInfo":
            self.session = {k: m.get(k) for k in (
                "session_id", "provider", "provider_session_key", "provider_meeting_key",
                "meeting_name", "year", "session_type", "session_name",
                "circuit_short_name", "country_code", "country_name", "location",
                "gmt_offset", "date_start", "date_end")}
        elif mtype == "Driver" and env.driver_number is not None:
            team = m.get("team") or {}
            self._drivers[int(env.driver_number)] = {
                "driver_number": int(env.driver_number),
                "acronym": m.get("name_acronym"),
                "full_name": m.get("full_name"),
                "broadcast_name": m.get("broadcast_name"),
                "team_id": team.get("team_id"),
                "team_name": team.get("display_name"),
                "team_colour": team.get("colour_hex"),   # verbatim provider hex
            }
        elif mtype == "TyreStint":
            key = (int(m["driver_number"]), int(m["stint_number"]))
            self._stints[key] = {
                "driver_number": key[0], "stint_number": key[1],
                "compound": m.get("compound"), "lap_start": m.get("lap_start"),
                "lap_end": m.get("lap_end"), "tyre_age_at_start": m.get("tyre_age_at_start"),
            }
        elif mtype == "PitStop":
            d = int(m["driver_number"])
            self._pit_counts[d] = self._pit_counts.get(d, 0) + 1
            self._pits.append({
                "driver_number": d, "ts": m.get("ts"), "lap_number": m.get("lap_number"),
                "lane_duration_s": m.get("lane_duration_s"),
                "stop_duration_s": m.get("stop_duration_s"), "frame_index": pending,
            })
        elif mtype == "RaceControlEvent":
            self._rcm.append({
                "ts": m.get("ts"), "lap_number": m.get("lap_number"),
                "category": m.get("category"), "flag": m.get("flag"),
                "scope": m.get("scope"), "marshal_sector": m.get("marshal_sector"),
                "driver_number": m.get("driver_number"), "message": m.get("message"),
                "rcm_key": m.get("rcm_key"), "frame_index": pending,
            })
        elif mtype == "WeatherPoint":
            self._weather.append({
                "ts": m.get("ts"), "air_temp_c": m.get("air_temp_c"),
                "track_temp_c": m.get("track_temp_c"), "humidity_pct": m.get("humidity_pct"),
                "pressure_hpa": m.get("pressure_hpa"), "rainfall": m.get("rainfall"),
                "wind_direction_deg": m.get("wind_direction_deg"),
                "wind_speed_mps": m.get("wind_speed_mps"), "frame_index": pending,
            })

    def _on_event(self, ev) -> None:   # ev: IntelligenceEvent
        if ev.event_type not in TIMELINE_EVENT_TYPES or ev.event_key in self._event_keys:
            return
        self._event_keys.add(ev.event_key)
        # provenance.calculated_at is wall-clock: left out so builds are repeatable
        self._events.append({
            "event_key": ev.event_key, "event_type": ev.event_type,
            "timestamp": ev.timestamp.isoformat(), "drivers": list(ev.driver_numbers),
            "severity": ev.severity.value, "metrics": ev.metrics,
            "evidence": list(ev.evidence), "frame_index": len(self.frames),
        })

    # -------------------------------------------------------------- capture --

    def capture(self, kind: str, lap: int | None, at: datetime | None) -> dict:
        eng = self.engine
        eng.flush_deferred()   # the hub flushes before every publish; same here
        snap = eng.snapshot_dict()
        rows = []
        for r in snap["leaderboard"]:
            num = r["driver_number"]
            pos = r["position"]
            prev = self._prev_positions.get(num)
            stint = eng.stints.current(num)
            rec = self._stints.get((num, stint.stint_number)) if stint else None
            lap_no = r["lap_number"]
            stint_laps = (max(0, lap_no - stint.lap_start + 1)
                          if stint and stint.lap_start is not None and lap_no is not None
                          else None)
            age0 = rec["tyre_age_at_start"] if rec else None
            sec = eng.sectors.drivers.get(num)
            rows.append({
                **r,
                "position_change": (prev - pos) if prev is not None and pos is not None
                else None,
                "pit_stops": self._pit_counts.get(num, 0),
                "stint_laps_completed": stint_laps,
                "tyre_age_at_start": age0,
                "tyre_laps_on_set": (age0 + stint_laps)
                if age0 is not None and stint_laps is not None else None,
                "sectors_last": ({f"S{k}": {"time_s": v, "status": sec.last_class.get(k)}
                                  for k, v in sorted(sec.last.items())} if sec else {}),
            })
        self._prev_positions = {row["driver_number"]: row["position"] for row in rows}
        frame = {
            "index": len(self.frames), "kind": kind, "lap": lap, "at": _iso(at),
            "phase": snap["phase"], "track_flag": snap["track_flag"],
            "current_lap": snap["current_lap"], "fastest_lap": snap["fastest_lap"],
            "sector_leaders": snap["sector_leaders"], "weather": snap["weather"],
            "active_battles": snap["active_battles"], "rows": rows,
        }
        self.frames.append(frame)
        if kind == "LAP" and lap is not None:
            self.last_lap_frame = max(self.last_lap_frame, lap)
        return frame

    # --------------------------------------------------------------- output --

    def input_digest(self) -> str:
        return "sha256:" + self._digest.hexdigest()

    def to_dict(self, *, source: dict, unplaced_stints: int = 0) -> dict:
        stints = [self._stints[k] for k in sorted(self._stints)]
        by_driver: dict[int, list[dict]] = {}
        for s in stints:
            by_driver.setdefault(s["driver_number"], []).append(s)
        pits = []
        for p in self._pits:
            before = after = None
            if p["lap_number"] is not None:
                lap_no = int(p["lap_number"])
                for s in by_driver.get(p["driver_number"], []):
                    if s["lap_start"] is not None and s["lap_start"] <= lap_no and \
                            (s["lap_end"] is None or lap_no <= s["lap_end"]):
                        before = s
                    if s["lap_start"] == lap_no + 1:
                        after = s
            pits.append({**p,
                         "stint_before": before["stint_number"] if before else None,
                         "compound_before": before["compound"] if before else None,
                         "stint_after": after["stint_number"] if after else None,
                         "compound_after": after["compound"] if after else None})
        return {
            "contract_version": CONTRACT_VERSION,
            "builder_version": BUILDER_VERSION,
            "calc_version": CALC_VERSION,
            "profile": self.engine.ctx.profile.value if self.engine.ctx.profile else None,
            "session": self.session,
            "source": {**source, "envelopes_folded": self.folded,
                       "unplaced_stints": unplaced_stints,
                       "input_digest": self.input_digest()},
            "drivers": [self._drivers[k] for k in sorted(self._drivers)],
            "laps_completed_max": self.last_lap_frame or None,
            "frames": self.frames,
            "stints": stints,
            "pit_stops": pits,
            "race_control": self._rcm,
            "weather": self._weather,
            "events": self._events,
            "capabilities": {
                "drs_availability": bool(self.engine.drs.supported),
                "undercut_overcut": False,
                "track_geometry": False,
                "retirement_status": False,
                "scheduled_race_distance": False,
            },
            "limitations": limitations(unplaced_stints),
        }


def limitations(unplaced_stints: int = 0) -> list[dict]:
    out = [
        {"code": "FRAME_AT_LEADER_LAP_END",
         "message": "Each LAP frame is the moment the leader completes that lap; every "
                    "other car is part-way through its own lap."},
        {"code": "LATEST_SAMPLE_AT_FRAME",
         "message": "Gaps, intervals and positions are the latest samples at the frame "
                    "moment; a gap can lag a position change by a few seconds (e.g. a car "
                    "that has just lost the lead may still show its leader interval)."},
        {"code": "RACE_ORDER_RECONSTRUCTED",
         "message": "Recorded envelopes are folded in race order by documented "
                    "effective-time rules, not in the order they were fetched."},
        {"code": "SCHEDULED_DISTANCE_NOT_RECORDED",
         "message": "The provider does not state the scheduled lap count; the lap count "
                    "shown is the most laps completed in the data."},
        {"code": "RETIREMENT_NOT_REPORTED",
         "message": "The feed has no retirement status; a retired car's lap count "
                    "simply stops increasing."},
        {"code": "DRS_AVAILABILITY_UNAVAILABLE",
         "message": "DRS availability is not provided by this data source."},
        {"code": "UNDERCUT_OVERCUT_NOT_PROVIDED",
         "message": "No validated undercut/overcut classification exists in the backend."},
        {"code": "NO_TRACK_GEOMETRY",
         "message": "No validated circuit geometry: no track map, corners or car "
                    "positions on track."},
        {"code": "SYMBOLIC_GAPS_VERBATIM",
         "message": "Lapped gaps such as '+1 LAP' are kept verbatim and never "
                    "converted to seconds."},
    ]
    if unplaced_stints:
        out.append({"code": "STINTS_UNPLACED",
                    "message": f"{unplaced_stints} stint record(s) could not be placed in "
                               "race order and were folded after all other data."})
    return out


# --------------------------------------------------------------- building --

def build_timeline(envelopes: Iterable[Envelope], *, source: dict) -> dict:
    """Offline build: order, fold, capture START / LAP k / FINAL."""
    envs = [e for e in envelopes if _model(e).get("type") not in SKIPPED_MODEL_TYPES]
    ordered, unplaced = order_for_replay(envs)
    session_id = next((_model(e).get("session_id") for e in envs
                       if _model(e).get("type") == "SessionInfo"),
                      envs[0].session_id if envs else "unknown")
    recorder = TimelineRecorder(AnalysisEngine(session_id=session_id))
    t0 = race_start_time(envs)
    started = t0 is None
    for at, env in ordered:
        if not started and at is not None and at > t0:
            recorder.capture("START", 0, t0)
            started = True
        recorder.fold(env, at)
    if not started:
        recorder.capture("START", 0, t0)
    last_at = next((at for at, _e in reversed(ordered) if at is not None), None)
    recorder.capture("FINAL", recorder.engine.snapshot_dict()["current_lap"], last_at)
    return recorder.to_dict(source=source, unplaced_stints=unplaced)


def iter_recording_envelopes(frames_path: Path,
                             skip_model_types: frozenset[str] = SKIPPED_MODEL_TYPES,
                             counts: dict | None = None) -> Iterator[Envelope]:
    """Stream a recording's envelopes (format: app.ingest.recorder), skipping
    the given model types before JSON parsing. `counts` receives totals."""
    from zstandard import ZstdDecompressor

    markers = [f'"type":"{t}"'.encode() for t in skip_model_types]
    total = skipped = 0
    with open(frames_path, "rb") as fh:
        reader = ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        for raw in io.BufferedReader(reader):
            if not raw.strip():
                continue
            total += 1
            if any(mk in raw for mk in markers):
                skipped += 1
                continue
            yield Envelope.model_validate(json.loads(raw)["envelope"])
    if counts is not None:
        counts.update({"envelopes_in_recording": total, "envelopes_skipped_telemetry": skipped})


def build_timeline_from_recording(recording_dir: Path) -> dict:
    recording_dir = Path(recording_dir)
    counts: dict = {}
    envs = list(iter_recording_envelopes(recording_dir / "frames.jsonl.zst", counts=counts))
    provider = next((_model(e).get("provider") for e in envs
                     if _model(e).get("type") == "SessionInfo"), None)
    source = {"kind": "RECORDING", "recording": recording_dir.name,
              "provider": provider, **counts}
    return build_timeline(envs, source=source)


def to_canonical_json(timeline: dict) -> bytes:
    """Sorted keys, no whitespace, NaN refused (fail closed)."""
    return json.dumps(timeline, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


# ------------------------------------------------------------- validation --

class TimelineContractError(ValueError):
    """The timeline violates session_timeline_v1; it must not be served."""


_KIND_ORDER = {"START": 0, "LAP": 1, "FINAL": 2}


def validate_timeline(tl: dict) -> None:
    """Structural invariants of session_timeline_v1. Raises TimelineContractError.

    Checks what a consumer relies on: frame order, one row per driver, unique
    positions, battles only between neighbours, references into frames, and
    no NaN/Infinity anywhere.
    """
    def fail(msg: str) -> None:
        raise TimelineContractError(msg)

    if tl.get("contract_version") != CONTRACT_VERSION:
        fail(f"contract_version must be {CONTRACT_VERSION}")
    frames = tl.get("frames") or []
    if not frames:
        fail("no frames")
    known = {d["driver_number"] for d in tl.get("drivers") or []}
    prev_kind, prev_lap, prev_at = -1, -1, None
    for i, f in enumerate(frames):
        if f.get("index") != i:
            fail(f"frame {i}: index {f.get('index')}")
        kind = _KIND_ORDER.get(f.get("kind"))
        if kind is None or kind < prev_kind or (kind == prev_kind and kind != 1):
            fail(f"frame {i}: kind {f.get('kind')} out of order")
        if f["kind"] == "LAP" and (f.get("lap") is None or f["lap"] <= prev_lap):
            fail(f"frame {i}: LAP frames must have strictly increasing laps")
        at = _dt(f.get("at"))
        if at is not None and prev_at is not None and at < prev_at:
            fail(f"frame {i}: moment goes backwards")
        prev_kind, prev_at = kind, at or prev_at
        if f["kind"] == "LAP":
            prev_lap = f["lap"]
        nums = [r["driver_number"] for r in f.get("rows", [])]
        if len(nums) != len(set(nums)):
            fail(f"frame {i}: a driver appears twice")
        if known and not set(nums) <= known:
            fail(f"frame {i}: rows for drivers not in the driver list")
        positions = {r["driver_number"]: r["position"] for r in f.get("rows", [])
                     if r.get("position") is not None}
        if len(set(positions.values())) != len(positions):
            fail(f"frame {i}: two drivers share a position")
        by_pos = {p: n for n, p in positions.items()}
        ordered = sorted(by_pos)
        ahead_of = {by_pos[q]: by_pos[p] for p, q in pairwise(ordered)}
        for b in f.get("active_battles", []):
            if ahead_of.get(b["behind"]) != b["ahead"]:
                fail(f"frame {i}: battle {b['ahead']}-{b['behind']} is not between neighbours")
    for key in ("pit_stops", "race_control", "weather", "events"):
        for item in tl.get(key) or []:
            fi = item.get("frame_index")
            if fi is None or not 0 <= fi <= len(frames):
                fail(f"{key}: frame_index {fi} out of range")
    try:
        to_canonical_json(tl)
    except ValueError as exc:
        fail(f"not serializable as strict JSON: {exc}")
