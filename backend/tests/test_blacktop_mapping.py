"""Blacktop raw rows -> canonical models, against REAL recorded responses.

Fixture: tests/fixtures/blacktop/2023-singapore-grand-prix/ (recorded by
scripts/record_blacktop_fixtures.py, verbatim bodies). Expected values are
facts checked against Jolpica and OpenF1 on 2026-09-25, not model output.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.enums import ProvenanceClass, ProviderName, SessionStatus, SessionType
from app.providers.blacktop.mapping import (
    event_to_sessions,
    quali_row_to_result,
    race_row_to_result,
    standing_row_to_entry,
)

FX = Path(__file__).parent / "fixtures" / "blacktop" / "2023-singapore-grand-prix"
EVENT_ID = "bf247ed6-cb57-4877-bb5b-9168a4e165a5"
RACE_SID = "cb7ae1d1-a437-4052-8ba1-369d9f88d144"


def _load(name: str):
    path = FX / name
    if not path.exists():
        pytest.skip(f"real Blacktop fixture missing: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _by_name(rows, last):
    return next(r for r in rows if r["driver"]["lastName"] == last)


def test_event_maps_to_one_session_per_schedule_entry():
    sessions = event_to_sessions(_load("event.json"))
    assert [s.session_name for s in sessions] == ["FP1", "FP2", "FP3", "Qualifying", "Race"]
    assert [s.session_type for s in sessions] == [
        SessionType.PRACTICE, SessionType.PRACTICE, SessionType.PRACTICE,
        SessionType.QUALIFYING, SessionType.RACE]
    race = sessions[-1]
    assert race.session_id == f"blacktop:{EVENT_ID}/{RACE_SID}"
    assert race.provider is ProviderName.BLACKTOP
    assert race.provider_meeting_key == EVENT_ID
    assert race.year == 2023
    assert race.meeting_name == "Singapore Grand Prix"
    assert race.circuit_short_name == "Marina Bay Street Circuit"
    assert race.country_code == "SGP"
    assert race.date_start == datetime(2023, 9, 17, 12, 0, tzinfo=UTC)
    assert race.status is SessionStatus.FINISHED
    assert race.provenance.provenance_class is ProvenanceClass.B


def test_sprint_types_seen_in_real_2023_list_map_explicitly():
    events = _load("events.json")
    seen = {s.session_type for e in events for s in event_to_sessions(e)}
    assert SessionType.SPRINT in seen
    assert SessionType.SPRINT_QUALI in seen
    assert SessionType.UNKNOWN not in seen


def test_cancelled_event_is_cancelled_not_finished():
    events = _load("events.json")
    imola = next(e for e in events if e["name"] == "Emilia Romagna Grand Prix")
    assert imola["status"] == "cancelled"
    # No sessions were ever scheduled -> nothing is invented for it.
    assert event_to_sessions(imola) == []


def test_cancelled_session_is_flagged():
    ev = {"id": "e", "name": "X", "dateStart": "2030-01-01", "status": "cancelled",
          "schedule": [{"id": "s", "type": "race", "name": "Race",
                        "startTime": "2030-01-03T12:00:00+00:00",
                        "endTime": "2030-01-03T14:00:00+00:00", "status": "scheduled"}]}
    (s,) = event_to_sessions(ev)
    assert s.is_cancelled is True
    assert s.status is SessionStatus.CANCELLED


def test_unknown_session_type_stays_unknown():
    ev = {"id": "e", "name": "X", "dateStart": "2030-01-01", "status": "scheduled",
          "schedule": [{"id": "s", "type": "hyperpole", "name": "Hyperpole",
                        "startTime": None, "endTime": None, "status": "scheduled"}]}
    (s,) = event_to_sessions(ev)
    assert s.session_type is SessionType.UNKNOWN
    assert s.date_start is None


def test_race_winner_maps_verbatim():
    r = race_row_to_result(_by_name(_load("results_race.json"), "Sainz"), "sid")
    assert (r.position, r.driver_number, r.family_name) == (1, 55, "Sainz")
    assert r.points == 25.0
    assert r.laps_completed == 62
    assert r.finish_time_raw == "1:46:37.418"
    assert r.fastest_lap_raw == "1:37.666"
    assert r.status_text == "OK"
    assert r.provenance.provider is ProviderName.BLACKTOP


def test_driver_number_is_the_car_number_of_that_session():
    # Verstappen raced as #1 in 2023. carNumber is session-specific. (In these
    # results rows driver.number also says 1 - reading it instead is an
    # equivalent mutant on this data; the STANDINGS `number` is the one that
    # is current-not-historical, asserted below.)
    r = race_row_to_result(_by_name(_load("results_race.json"), "Verstappen"), "sid")
    assert r.driver_number == 1


def test_standings_number_is_current_not_historical_so_it_is_not_identity():
    rows = _load("standings_drivers.json")
    by_last = {r["lastName"]: r for r in rows}
    assert by_last["Verstappen"]["number"] == 3  # raced 2023 as #1
    assert by_last["Ricciardo"]["number"] == 3   # two drivers, one number
    entry = standing_row_to_entry(by_last["Verstappen"], 2023)
    assert "number" not in entry.model_dump()


def test_retirement_laps_are_not_reported_as_completed():
    # Blacktop gives laps = Jolpica + 1 for every retirement (Russell 62 vs 61,
    # Bottas 52/51, Ocon 43/42, Tsunoda 1/0): laps STARTED, not completed.
    rows = _load("results_race.json")
    for last in ("Russell", "Bottas", "Ocon", "Tsunoda"):
        r = race_row_to_result(_by_name(rows, last), "sid")
        assert r.laps_completed is None, last
        assert r.finish_time_raw is None, last  # "DNF" is a status, not a time
        assert r.status_text == "DNF"


def test_unclassified_position_is_none_not_a_number():
    r = race_row_to_result(_by_name(_load("results_race.json"), "Ocon"), "sid")
    assert r.position is None


def test_quali_times_map_verbatim():
    q = quali_row_to_result(_by_name(_load("results_qualifying.json"), "Sainz"), "sid")
    assert (q.position, q.driver_number) == (1, 55)
    assert (q.q1_raw, q.q2_raw, q.q3_raw) == ("1:32.339", "1:31.439", "1:30.984")
    t = quali_row_to_result(_by_name(_load("results_qualifying.json"), "Tsunoda"), "sid")
    assert (t.q2_raw, t.q3_raw) == (None, None)


def test_standings_entry_has_no_invented_round_or_wins():
    rows = _load("standings_drivers.json")
    ver = standing_row_to_entry(next(r for r in rows if r["lastName"] == "Verstappen"), 2023)
    assert ver.season == 2023
    assert ver.position == 1
    assert ver.points == 556.0  # verbatim upstream - crosscheck flags Jolpica's 575
    assert ver.round_after is None
    assert ver.wins is None
    assert ver.provenance.provider is ProviderName.BLACKTOP
