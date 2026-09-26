"""Session lap timeline (Phase 11) - mechanics on small synthetic races.

Synthetic data here only exercises ordering and capture rules; the real-data
evidence is tests/test_session_timeline_real.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.analysis.timeline import (
    CONTRACT_VERSION,
    TimelineContractError,
    build_timeline,
    order_for_replay,
    to_canonical_json,
    validate_timeline,
)
from app.core.events import Envelope

T0 = datetime(2026, 8, 23, 13, 0, 0, tzinfo=UTC)
PROV = {"provider": "openf1", "provenance_class": "B"}


def env(mtype: str, data: dict, ts: datetime | None, driver: int | None = None) -> Envelope:
    return Envelope(event_type="x", session_id="s", source="test", driver_number=driver,
                    source_timestamp=ts, ingestion_timestamp=T0, provenance_class="B",
                    payload={"model": {"type": mtype, **data}})


def session() -> Envelope:
    return env("SessionInfo", {"session_id": "s", "provider": "openf1",
                               "provider_session_key": "1", "session_type": "Race",
                               "year": 2026, "circuit_short_name": "Test",
                               "provenance": PROV}, T0)


def driver(n: int, code: str) -> Envelope:
    return env("Driver", {"driver_id": f"d{n}", "full_name": code, "name_acronym": code,
                          "team": {"team_id": "t", "display_name": "Team",
                                   "colour_hex": "112233", "provenance": PROV},
                          "provenance": PROV}, None, driver=n)


def lap(d: int, n: int, start: float, dur: float | None) -> Envelope:
    s = T0 + timedelta(seconds=start)
    return env("Lap", {"session_id": "s", "driver_number": d, "lap_number": n,
                       "started_at": s.isoformat(), "duration_s": dur,
                       "sector1_s": None, "sector2_s": None, "sector3_s": None,
                       "is_pit_out_lap": False, "deleted": False,
                       "speed_traps": {"i1_kph": None, "i2_kph": None, "st_kph": None},
                       "provenance": PROV}, s, driver=d)


def position(d: int, p: int, at: float) -> Envelope:
    t = T0 + timedelta(seconds=at)
    return env("PositionUpdate", {"session_id": "s", "driver_number": d, "ts": t.isoformat(),
                                  "position": p, "provenance": PROV}, t, driver=d)


def stint(d: int, n: int, compound: str, start: int, end: int | None, age: int) -> Envelope:
    return env("TyreStint", {"session_id": "s", "driver_number": d, "stint_number": n,
                             "compound": compound, "lap_start": start, "lap_end": end,
                             "tyre_age_at_start": age, "provenance": PROV}, None, driver=d)


def pit(d: int, at: float, lap_no: int) -> Envelope:
    t = T0 + timedelta(seconds=at)
    return env("PitStop", {"session_id": "s", "driver_number": d, "ts": t.isoformat(),
                           "lap_number": lap_no, "lane_duration_s": 20.0,
                           "stop_duration_s": None, "provenance": PROV}, t, driver=d)


def rcm(at: float, message: str, flag: str | None = None) -> Envelope:
    t = T0 + timedelta(seconds=at)
    return env("RaceControlEvent", {"session_id": "s", "ts": t.isoformat(),
                                     "category": "Flag" if flag else "Other", "flag": flag,
                                     "message": message, "rcm_key": f"k{at}",
                                     "provenance": PROV}, t)


def race() -> list[Envelope]:
    """Two cars, three laps, recorded in fetch order (laps first, stints last).

    Car 1 leads; car 2 pits after lap 1 (SOFT -> HARD, set already 2 laps old).
    Leader lap boundaries: L1 100 s, L2 200 s, L3 300 s.
    """
    return [
        session(), driver(1, "AAA"), driver(2, "BBB"),
        lap(1, 1, 0, 100.0), lap(1, 2, 100, 100.0), lap(1, 3, 200, 100.0),
        lap(2, 1, 1, 101.0), lap(2, 2, 102, 120.0), lap(2, 3, 222, 99.0),
        position(1, 1, -600), position(2, 2, -600),        # grid, before the start
        pit(2, 110, 1),
        rcm(150, "YELLOW IN TRACK SECTOR 4", "YELLOW"),
        stint(1, 1, "MEDIUM", 1, 3, 0),
        stint(2, 1, "SOFT", 1, 1, 0), stint(2, 2, "HARD", 2, 3, 2),
    ]


def build() -> dict:
    return build_timeline(race(), source={"kind": "SYNTHETIC"})


def frame(tl: dict, kind: str, lap_no: int) -> dict:
    return next(f for f in tl["frames"] if f["kind"] == kind and f["lap"] == lap_no)


def row(f: dict, d: int) -> dict:
    return next(r for r in f["rows"] if r["driver_number"] == d)


def _key(e: Envelope) -> tuple:
    m = e.payload["model"]
    return (m["type"], m.get("driver_number"), m.get("stint_number"), m.get("lap_number"))


# ---------------------------------------------------------------- ordering --

def test_laps_are_placed_at_completion_and_stints_at_their_first_lap_start():
    ordered, unplaced = order_for_replay(race())
    assert unplaced == 0
    assert [_key(e)[0] for _t, e in ordered[:3]] == ["SessionInfo", "Driver", "Driver"]
    at = {_key(e): t for t, e in ordered}
    assert at[("Lap", 1, None, 1)] == T0 + timedelta(seconds=100)   # completion, not start
    # car 2's HARD stint (lap_start 2) lands at car 2's lap-2 start (102 s)
    assert at[("TyreStint", 2, 2, None)] == T0 + timedelta(seconds=102)
    # the starting tyre goes before everything timed, even when the driver's
    # lap-1 row carries a later start (a car that stopped on lap 1)
    assert at[("TyreStint", 2, 1, None)] is None
    late = [lap(4, 1, 1800, None), position(4, 4, 5), stint(4, 1, "SOFT", 1, 1, 0)]
    ordered, _ = order_for_replay(late)
    assert _key(ordered[0][1]) == ("TyreStint", 4, 1, None) and ordered[0][0] is None


def test_a_stint_that_cannot_be_placed_is_folded_last_and_counted():
    envs = race() + [stint(3, 2, "HARD", 30, None, 0)]
    ordered, unplaced = order_for_replay(envs)
    assert unplaced == 1
    assert ordered[-1][1].payload["model"]["driver_number"] == 3


def test_ties_keep_recording_order():
    a, b = position(1, 1, 50), position(2, 2, 50)
    ordered, _ = order_for_replay([a, b])
    assert [e for _t, e in ordered] == [a, b]


# ----------------------------------------------------------------- frames --

def test_frames_are_start_then_each_leader_lap_then_final():
    tl = build()
    assert tl["contract_version"] == CONTRACT_VERSION
    assert [(f["kind"], f["lap"]) for f in tl["frames"]] == [
        ("START", 0), ("LAP", 1), ("LAP", 2), ("LAP", 3), ("FINAL", 3)]
    assert frame(tl, "LAP", 2)["at"] == (T0 + timedelta(seconds=200)).isoformat()
    validate_timeline(tl)


def test_start_frame_has_the_grid_and_no_laps():
    f = frame(build(), "START", 0)
    assert [(r["position"], r["driver_number"]) for r in f["rows"]] == [(1, 1), (2, 2)]
    assert all(r["lap_number"] is None for r in f["rows"])


def test_a_lap_frame_is_the_leaders_crossing_other_cars_are_mid_lap():
    f = frame(build(), "LAP", 1)
    assert row(f, 1)["lap_number"] == 1
    assert row(f, 2)["lap_number"] is None      # car 2 finishes lap 1 at 102 s


def test_no_future_facts_leak_into_a_frame():
    tl = build()
    # the pit at 110 s is after LAP 1 (100 s): LAP 1 must not know about it
    assert row(frame(tl, "LAP", 1), 2)["pit_stops"] == 0
    assert row(frame(tl, "LAP", 2), 2)["pit_stops"] == 1
    # tyre: car 2 is on SOFT at LAP 1, HARD once its lap-2 stint starts
    assert row(frame(tl, "LAP", 1), 2)["compound"] == "SOFT"
    assert row(frame(tl, "LAP", 2), 2)["compound"] == "HARD"
    # the yellow at 150 s shows from LAP 2 on (no race-control message before it)
    assert frame(tl, "LAP", 1)["track_flag"] == "UNKNOWN"
    assert frame(tl, "LAP", 2)["track_flag"] == "YELLOW"


def test_facts_point_at_the_first_frame_that_includes_them():
    tl = build()
    assert [p["frame_index"] for p in tl["pit_stops"]] == [2]        # LAP 2
    assert [m["frame_index"] for m in tl["race_control"]] == [2]


def test_tyre_age_on_set_adds_the_age_at_fit():
    r = row(frame(build(), "LAP", 3), 2)       # car 2 has completed lap 2 on HARD
    assert r["lap_number"] == 2 and r["stint_laps_completed"] == 1
    assert r["tyre_age_at_start"] == 2 and r["tyre_laps_on_set"] == 3


def test_pit_stop_lists_the_compounds_either_side_from_stints():
    p = build()["pit_stops"][0]
    assert (p["stint_before"], p["compound_before"]) == (1, "SOFT")
    assert (p["stint_after"], p["compound_after"]) == (2, "HARD")


def test_pit_without_a_following_stint_names_no_compound_after():
    envs = [e for e in race() if _key(e) != ("TyreStint", 2, 2, None)]
    p = build_timeline(envs, source={"kind": "SYNTHETIC"})["pit_stops"][0]
    assert p["compound_after"] is None and p["stint_after"] is None


def test_position_change_is_against_the_previous_frame():
    envs = race() + [position(2, 1, 250), position(1, 2, 250)]   # swap before L3
    tl = build_timeline(envs, source={"kind": "SYNTHETIC"})
    assert row(frame(tl, "LAP", 3), 2)["position_change"] == 1
    assert row(frame(tl, "LAP", 3), 1)["position_change"] == -1
    assert row(frame(tl, "START", 0), 1)["position_change"] is None


def test_drivers_keep_provider_identity_verbatim():
    assert build()["drivers"][0] == {
        "driver_number": 1, "acronym": "AAA", "full_name": "AAA", "broadcast_name": None,
        "team_id": "t", "team_name": "Team", "team_colour": "112233"}


def test_build_is_deterministic_and_does_not_depend_on_fetch_order():
    a = to_canonical_json(build())
    assert a == to_canonical_json(build())
    shuffled = build_timeline(list(reversed(race())), source={"kind": "SYNTHETIC"})
    assert [f["rows"] for f in shuffled["frames"]] == \
        [f["rows"] for f in json.loads(a)["frames"]]


def test_telemetry_is_skipped_and_cannot_change_frames():
    car = env("TelemetryCarSample", {"session_id": "s", "driver_number": 1,
                                     "ts": (T0 + timedelta(seconds=5)).isoformat(),
                                     "speed_kph": 300, "provenance": PROV},
              T0 + timedelta(seconds=5), driver=1)
    with_tel = build_timeline(race() + [car], source={"kind": "SYNTHETIC"})
    assert with_tel["frames"] == build()["frames"]
    assert with_tel["source"]["envelopes_folded"] == build()["source"]["envelopes_folded"]


# ------------------------------------------------------------- validation --

def _broken(mutate) -> dict:
    tl = json.loads(to_canonical_json(build()))
    mutate(tl)
    return tl


@pytest.mark.parametrize("mutate", [
    lambda t: t.update(contract_version="session_timeline_v0"),
    lambda t: t["frames"][1].update(index=7),
    lambda t: t["frames"][2].update(lap=1),
    lambda t: t["frames"][0].update(kind="FINAL"),
    lambda t: t["frames"][2].update(at=t["frames"][0]["at"]),
    lambda t: t["frames"][1]["rows"].append(t["frames"][1]["rows"][0]),
    lambda t: t["frames"][1]["rows"][1].update(position=1),
    lambda t: t["frames"][1]["rows"][1].update(driver_number=99),
    lambda t: t["frames"][1]["active_battles"].append(
        {"ahead": 2, "behind": 1, "state": "ACTIVE_BATTLE"}),
    lambda t: t["pit_stops"][0].update(frame_index=99),
    lambda t: t["frames"][1]["rows"][0].update(interval_s=float("nan")),
], ids=["contract", "index", "lap order", "kind order", "time backwards",
        "duplicate driver", "shared position", "unknown driver", "battle not neighbours",
        "dangling reference", "NaN"])
def test_validation_fails_closed(mutate):
    with pytest.raises(TimelineContractError):
        validate_timeline(_broken(mutate))


def test_laps_show_before_any_tyre_or_pit_data_arrives():
    # the engine defers laps until stint/pit context; the hub flushes before
    # every publish and the recorder flushes before every capture
    envs = [e for e in race() if _key(e)[0] not in ("TyreStint", "PitStop")]
    tl = build_timeline(envs, source={"kind": "SYNTHETIC"})
    assert row(frame(tl, "LAP", 1), 1)["lap_number"] == 1
    assert row(frame(tl, "LAP", 2), 1)["last_lap_s"] == 100.0


def test_a_stop_without_a_tyre_change_names_no_compound_after():
    # car 2 stops again at the end of lap 2 (e.g. a penalty); its next stint
    # starts on lap 4, not lap 3, so that stop records no change - it must not
    # borrow the later stint's tyre
    envs = race() + [pit(2, 225, 2), stint(2, 3, "MEDIUM", 4, None, 0)]
    tl = build_timeline(envs, source={"kind": "SYNTHETIC"})
    second = next(p for p in tl["pit_stops"] if p["lap_number"] == 2)
    assert (second["compound_before"], second["compound_after"]) == ("HARD", None)
