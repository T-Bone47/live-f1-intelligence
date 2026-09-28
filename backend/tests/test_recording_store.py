"""Phase 12C Task 1: laps and car/location telemetry served from a recording.

Synthetic recordings (tests/spatial_synth.py) only: these tests pin the
store's mechanics, never the real pipeline's correctness.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from spatial_synth import SID, T0, at, lap_row, row, synth_rows, write_recording

from app.spatial.source import SpatialIdentityError
from app.storage import recording_store
from app.storage.recording_store import RecordingStore

FULL = {"rpm": 11000, "speed_kph": 280, "gear": 7, "throttle_pct": 100.0,
        "brake_pct": 0.0, "drs": None}


def car(driver: int, seconds: float, sid: str = SID, **values):
    model = {"session_id": sid, "driver_number": driver, "ts": at(seconds).isoformat(),
             **FULL, **values,
             "provenance": {"provider": "openf1", "provenance_class": "B"}}
    return row("TelemetryCarSample", model, driver, sid)


def correction(driver: int, lap: int, kind: str):
    return row("LapCorrection", {"session_id": SID, "driver_number": driver, "lap_number": lap,
                                 "kind": kind, "reason": "TRACK LIMITS"}, driver)


def store_for(tmp_path, extra=(), laps=6):
    write_recording(tmp_path, synth_rows(laps=laps, extra=tuple(extra)))
    return RecordingStore(tmp_path)


def test_null_speed_round_trips_as_none(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0, speed_kph=None, throttle_pct=None, gear=None)])
    [s] = store.car_samples(SID, 1, at(9.0), at(11.0))
    assert s.speed_kph is None and s.throttle_pct is None and s.gear is None
    assert s.rpm == 11000 and s.brake_pct == 0.0 and s.drs is None


def test_identical_duplicate_collapses(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0), car(1, 10.0), car(1, 10.5)])
    assert [s.ts for s in store.car_samples(SID, 1, at(9.0), at(11.0))] == [at(10.0), at(10.5)]
    assert store.counts(SID)["car_duplicate_identical"] == 1


def test_conflicting_duplicate_dropped_and_counted(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0), car(1, 10.0, speed_kph=281), car(1, 10.5)])
    assert [s.ts for s in store.car_samples(SID, 1, at(9.0), at(11.0))] == [at(10.5)]
    assert store.counts(SID)["car_duplicate_conflicting"] == 2


def test_later_lap_row_wins(tmp_path):
    store = store_for(tmp_path, [lap_row(1, 2, at(60.0), 61.25)])
    assert store.lap(SID, 1, 2).duration_s == 61.25
    assert store.counts(SID)["lap_duplicates"] == 1


def test_lap_unknown_raises_lookup_error(tmp_path):
    store = store_for(tmp_path)
    with pytest.raises(LookupError):
        store.lap(SID, 1, 99)
    with pytest.raises(LookupError):
        store.lap(SID, 42, 1)


def test_deleted_true_only_from_correction_else_none(tmp_path):
    store = store_for(tmp_path, [correction(1, 2, "LAP_DELETED"),
                                 correction(1, 3, "LAP_DELETED"),
                                 correction(1, 3, "LAP_REINSTATED")])
    laps = {lap["lap_number"]: lap for lap in store.lap_catalog(SID)["drivers"][0]["laps"]}
    assert laps[2]["deleted"] is True
    assert laps[3]["deleted"] is False
    assert laps[4]["deleted"] is None  # recorded Lap.deleted=False is a default, not a fact


def test_other_session_row_raises_identity_error(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0, sid="openf1:2")])
    with pytest.raises(SpatialIdentityError, match="openf1:2"):
        store.car_samples(SID, 1, at(9.0), at(11.0))


def test_window_is_inclusive(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0), car(1, 10.25), car(1, 10.5), car(1, 10.75)])
    got = [s.ts for s in store.car_samples(SID, 1, at(10.25), at(10.5))]
    assert got == [at(10.25), at(10.5)]


def test_samples_are_attributed_to_their_own_driver(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0, speed_kph=111), car(2, 10.0, speed_kph=222)])
    assert [s.speed_kph for s in store.car_samples(SID, 2, at(9.0), at(11.0))] == [222]
    assert [s.driver_number for s in store.car_samples(SID, 1, at(9.0), at(11.0))] == [1]


def test_car_rows_match_the_database_row_shape(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0)])
    [r] = store.car_rows(SID, 1, at(9.0), at(11.0))
    assert set(r) == {"ts", "rpm", "speed_kph", "gear", "throttle_pct", "brake_pct", "drs",
                      "provenance_class"}
    assert r["ts"] == at(10.0) and r["provenance_class"] == "B"


def test_location_rows_are_raw_including_no_fix(tmp_path):
    loc = row("TelemetryLocationSample", {"session_id": SID, "driver_number": 1,
                                          "ts": at(1000.01).isoformat(), "x": 0.0, "y": 0.0,
                                          "z": 0.0}, 1)
    nul = row("TelemetryLocationSample", {"session_id": SID, "driver_number": 1,
                                          "ts": at(1000.02).isoformat(), "x": None, "y": 3.0,
                                          "z": 1.0}, 1)
    store = store_for(tmp_path, [loc, nul], laps=20)
    rows = store.location_rows(SID, 1, at(1000.0), at(1000.03))
    assert [(r["x"], r["y"], r["z"]) for r in rows if r["ts"] in (at(1000.01), at(1000.02))] \
        == [(0.0, 0.0, 0.0), (None, 3.0, 1.0)]


def test_has_car_telemetry_means_a_sample_inside_the_lap_window(tmp_path):
    # driver 1 lap 1 runs [0, 60] s: a sample exactly at its end counts (BETWEEN)
    store = store_for(tmp_path, [car(1, 60.0), lap_row(2, 7, at(900.0), None)])
    drivers = {d["driver_number"]: d for d in store.lap_catalog(SID)["drivers"]}
    flags = {lap["lap_number"]: lap["has_car_telemetry"] for lap in drivers[1]["laps"]}
    assert flags[1] is True and flags[2] is True and flags[3] is False
    no_duration = [lap for lap in drivers[2]["laps"] if lap["lap_number"] == 7]
    assert no_duration[0]["has_car_telemetry"] is False


def test_catalog_keys_match_repository_shape(tmp_path):
    body = store_for(tmp_path).lap_catalog(SID)
    assert set(body) == {"session_id", "drivers"} and body["session_id"] == SID
    d = body["drivers"][0]
    assert set(d) == {"driver_number", "acronym", "full_name", "team_name", "team_colour",
                      "laps"}
    assert set(d["laps"][0]) == {"lap_number", "started_at", "duration_s", "deleted",
                                 "is_pit_out_lap", "has_car_telemetry"}
    assert d["acronym"] == "D1" and d["laps"][0]["started_at"] == T0


def test_session_source_from_recorded_session_info(tmp_path):
    src = store_for(tmp_path).session_source(SID)
    assert (src.session_id, src.provider, src.session_type, src.season, src.circuit) == \
        (SID, "openf1", "Race", 2026, "Synthetic")
    assert src.event is None  # not recorded: never looked up


def test_unknown_session_has_no_recording(tmp_path):
    store = store_for(tmp_path)
    assert store.recording_for("openf1:404") is None
    with pytest.raises(LookupError):
        store.lap_catalog("openf1:404")


def test_warm_load_reads_the_cache_not_the_recording(tmp_path, monkeypatch):
    store_for(tmp_path, [car(1, 10.0)]).counts(SID)

    def boom(*_a, **_k):
        raise AssertionError("recording re-read despite a valid cache")

    monkeypatch.setattr(recording_store, "iter_recording_models", boom)
    [s] = RecordingStore(tmp_path).car_samples(SID, 1, at(9.0), at(11.0))
    assert s.speed_kph == 280


def test_mtime_change_rebuilds(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0)])
    store.counts(SID)
    rec = store.recording_for(SID)
    key_file = rec / recording_store.KEY_NAME
    before = key_file.read_text(encoding="utf-8")
    frames = rec / "frames.jsonl.zst"
    st = frames.stat()
    os.utime(frames, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))
    [s] = RecordingStore(tmp_path).car_samples(SID, 1, at(9.0), at(11.0))
    assert s.speed_kph == 280 and key_file.read_text(encoding="utf-8") != before


def test_truncated_bin_rebuilds(tmp_path):
    store = store_for(tmp_path, [car(1, 10.0), car(1, 10.5)])
    store.counts(SID)
    binary = store.recording_for(SID) / recording_store.BIN_NAME
    size = binary.stat().st_size
    binary.write_bytes(binary.read_bytes()[: size // 2])
    got = RecordingStore(tmp_path).car_samples(SID, 1, at(9.0), at(11.0))
    assert [s.ts for s in got] == [at(10.0), at(10.5)] and binary.stat().st_size == size


def test_samples_carry_utc_timestamps(tmp_path):
    [s] = store_for(tmp_path, [car(1, 10.0)]).car_samples(SID, 1, at(9.0), at(11.0))
    assert s.ts.utcoffset() == timedelta(0) and s.ts.isoformat() == at(10.0).isoformat()
