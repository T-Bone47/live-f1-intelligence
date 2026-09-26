"""Session lap timeline on the REAL 2026 Dutch GP race (OpenF1 session 11353).

Real-data gate: needs the recording made by scripts/record_session.py
(recordings/**/openf1-11353-race with meta.json). Without it these tests skip;
the committed golden is still checked structurally by the frontend and by
test_golden_is_a_valid_timeline below.

Every frame is checked against values recomputed here straight from the raw
recorded rows - positions, intervals, lap counts, pit counts, compounds and
frame moments - without using the AnalysisEngine.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.timeline import (
    build_timeline_from_recording,
    iter_recording_envelopes,
    to_canonical_json,
    validate_timeline,
)

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "docs" / "timeline" / "session_timeline_v1_dutch_gp_2026.json"
NAME = "openf1-11353-race"


def _find_recording() -> Path | None:
    env = os.environ.get("F1INTEL_TIMELINE_RECORDING")
    candidates = [Path(env)] if env else sorted((REPO / "recordings").glob(f"**/{NAME}"))
    for c in candidates:
        if (c / "meta.json").exists() and (c / "frames.jsonl.zst").exists():
            return c
    return None


RECORDING = _find_recording()
needs_recording = pytest.mark.skipif(
    RECORDING is None, reason=f"real recording {NAME} (with meta.json) not present")


def _dt(v: str) -> datetime:
    return datetime.fromisoformat(v)


@pytest.fixture(scope="module")
def built() -> dict:
    return build_timeline_from_recording(RECORDING)


@pytest.fixture(scope="module")
def raw() -> dict:
    """Raw rows with their recording index (ties are broken by it)."""
    out: dict[str, list] = {"Lap": [], "PositionUpdate": [], "TimingInterval": [],
                            "PitStop": [], "TyreStint": [], "RaceControlEvent": []}
    for idx, env in enumerate(iter_recording_envelopes(RECORDING / "frames.jsonl.zst")):
        m = env.payload["model"]
        if m["type"] in out:
            out[m["type"]].append((idx, m))
    return out


def _lap_done(raw: dict) -> dict[tuple[int, int], tuple[datetime, int]]:
    done = {}
    for idx, m in raw["Lap"]:
        if m["duration_s"] is not None:
            done[(m["driver_number"], m["lap_number"])] = (
                _dt(m["started_at"]) + timedelta(seconds=m["duration_s"]), idx)
    return done


def _cutoffs(tl: dict, raw: dict) -> list[tuple[datetime, int] | None]:
    """(moment, recording index of the leader's lap row) per LAP frame; a fact
    is in the frame iff (ts, idx) sorts before it - race order, ties by index."""
    done = _lap_done(raw)
    return [min(v for (_d, n), v in done.items() if n == f["lap"]) if f["kind"] == "LAP"
            else None for f in tl["frames"]]


def _before(ts: datetime, idx: int, cut: tuple[datetime, int]) -> bool:
    return (ts, idx) < cut


@needs_recording
def test_real_timeline_is_valid_and_frames_every_lap(built):
    validate_timeline(built)
    kinds = [(f["kind"], f["lap"]) for f in built["frames"]]
    assert kinds[0] == ("START", 0) and kinds[-1][0] == "FINAL"
    assert [lap for k, lap in kinds if k == "LAP"] == list(range(1, 73))
    assert built["laps_completed_max"] == 72
    assert built["source"]["unplaced_stints"] == 0


@needs_recording
def test_lap_frame_moments_are_the_first_raw_lap_completion(built, raw):
    for f, cut in zip(built["frames"], _cutoffs(built, raw), strict=True):
        if cut is not None:
            assert _dt(f["at"]) == cut[0]


@needs_recording
def test_positions_equal_the_last_raw_position_row_before_each_frame(built, raw):
    for f, cut in zip(built["frames"], _cutoffs(built, raw), strict=True):
        if cut is None:
            continue
        expected: dict[int, int] = {}
        for idx, m in raw["PositionUpdate"]:
            if _before(_dt(m["ts"]), idx, cut):
                expected[m["driver_number"]] = m["position"]
        got = {r["driver_number"]: r["position"] for r in f["rows"]}
        assert got == expected, f"LAP {f['lap']}"


@needs_recording
def test_intervals_equal_the_last_raw_numeric_sample_before_each_frame(built, raw):
    checked = 0
    for f, cut in zip(built["frames"], _cutoffs(built, raw), strict=True):
        if cut is None:
            continue
        expected: dict[int, float] = {}
        for idx, m in raw["TimingInterval"]:
            if _before(_dt(m["ts"]), idx, cut) and m["interval_s"] is not None:
                expected[m["driver_number"]] = m["interval_s"]
        for r in f["rows"]:
            assert r["interval_s"] == expected.get(r["driver_number"]), \
                f"LAP {f['lap']} #{r['driver_number']}"
            checked += 1
    assert checked > 1000


@needs_recording
def test_lap_counts_and_pit_counts_match_raw_rows(built, raw):
    """A lap counts from its completion; a lap reported without a time counts
    from its start (e.g. #87's lap 3 during the 2026 Dutch GP red flag)."""
    counted = dict(_lap_done(raw))
    for idx, m in raw["Lap"]:
        if m["duration_s"] is None:
            counted[(m["driver_number"], m["lap_number"])] = (_dt(m["started_at"]), idx)
    for f, cut in zip(built["frames"], _cutoffs(built, raw), strict=True):
        if cut is None:
            continue
        for r in f["rows"]:
            d = r["driver_number"]
            laps = [n for (dd, n), v in counted.items() if dd == d and v <= cut]
            assert r["lap_number"] == (max(laps) if laps else None), f"LAP {f['lap']} #{d}"
            pits = sum(1 for idx, m in raw["PitStop"]
                       if m["driver_number"] == d and _before(_dt(m["ts"]), idx, cut))
            assert r["pit_stops"] == pits, f"LAP {f['lap']} #{d}"


@needs_recording
def test_compound_is_the_latest_stint_that_has_started(built, raw):
    """Independent rule, from raw rows: the starting stint (lap_start <= 1) is
    on from the start; a later stint starts when the driver's lap `lap_start`
    starts (its lap-start row). Compound = the latest started stint. Note: the
    provider stamps lap starts to the ms, so a new stint can begin a few ms
    before the previous lap's computed completion (#12, lap 22: 21 ms)."""
    starts = {(m["driver_number"], m["lap_number"]): (_dt(m["started_at"]), idx)
              for idx, m in raw["Lap"]}
    stints = {(m["driver_number"], m["stint_number"]): m for _i, m in raw["TyreStint"]}
    for f, cut in zip(built["frames"], _cutoffs(built, raw), strict=True):
        if cut is None:
            continue
        for r in f["rows"]:
            d = r["driver_number"]
            started = [s for (dd, _n), s in stints.items() if dd == d and (
                s["lap_start"] <= 1 or ((d, s["lap_start"]) in starts
                                        and starts[(d, s["lap_start"])][0] < cut[0]))]
            if not started:
                continue
            latest = max(started, key=lambda s: s["stint_number"])
            assert (r["compound"], r["stint_number"]) ==                 (latest["compound"], latest["stint_number"]), f"LAP {f['lap']} #{d}"


@needs_recording
def test_the_starting_grid_is_in_the_start_frame(built):
    start = built["frames"][0]
    assert sorted(r["position"] for r in start["rows"]) == list(range(1, 23))


@needs_recording
def test_the_lap_two_red_flag_is_recorded_as_observed(built):
    # verbatim message; OpenF1 sends no flag value with it
    assert any(m["message"] == "RED FLAG - RACE SUSPENDED" for m in built["race_control"])
    # the LAP 2 frame (13:06:56) falls inside the stoppage (13:05:28-13:33:00)
    lap2 = next(f for f in built["frames"] if f["kind"] == "LAP" and f["lap"] == 2)
    assert (lap2["phase"], lap2["track_flag"]) == ("RED_FLAG", "RED")
    lap3 = next(f for f in built["frames"] if f["kind"] == "LAP" and f["lap"] == 3)
    assert lap3["phase"] == "LIVE"
    long_stops = [p for p in built["pit_stops"]
                  if p["lap_number"] == 2 and p["lane_duration_s"] > 1000]
    assert len(long_stops) >= 15                 # cars waited in the pit lane
    nor = next(p for p in long_stops if p["driver_number"] == 1)
    assert (nor["compound_before"], nor["compound_after"]) == ("MEDIUM", "SOFT")


@needs_recording
def test_race_control_messages_point_at_the_first_frame_after_them(built):
    frames = built["frames"]
    for m in built["race_control"]:
        fi = m["frame_index"]
        ts = _dt(m["ts"])
        if 0 < fi < len(frames) and frames[fi]["kind"] == "LAP":
            assert ts <= _dt(frames[fi]["at"])
            assert ts >= _dt(frames[fi - 1]["at"])


@needs_recording
def test_real_build_matches_the_committed_golden(built):
    assert GOLDEN.exists(), "run scripts/timeline_report.py to create the golden"
    assert to_canonical_json(built) + b"\n" == GOLDEN.read_bytes()


def test_golden_is_a_valid_timeline():
    if not GOLDEN.exists():
        pytest.skip("golden not generated yet")
    validate_timeline(json.loads(GOLDEN.read_bytes()))
