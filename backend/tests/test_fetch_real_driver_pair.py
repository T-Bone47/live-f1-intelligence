"""Plumbing tests for scripts/fetch_real_driver_pair.py.

The stub client serves SYNTHETIC rows in OpenF1's shape. They exercise the
script's control flow (what aborts, what gets written) and are evidence of
nothing about real F1 telemetry.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.providers.openf1.client import OpenF1Error
from app.providers.openf1.real_data import IdentityMismatch

SCRIPTS = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("fetch_real_driver_pair",
                                               SCRIPTS / "fetch_real_driver_pair.py")
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)

SK = 1000  # synthetic session key


def _lap(d, n=5, dur=90.0, pit_out=False):
    return {"session_key": SK, "driver_number": d, "lap_number": n,
            "date_start": "2024-01-01T12:00:00+00:00", "lap_duration": dur,
            "is_pit_out_lap": pit_out}


def _car(d, sk=SK):
    return [{"session_key": sk, "driver_number": d, "date": "2024-01-01T12:00:01+00:00",
             "speed": 200, "throttle": 90, "brake": 0, "rpm": 11000, "n_gear": 7, "drs": 0}]


def _loc(d, sk=SK):
    return [{"session_key": sk, "driver_number": d, "date": "2024-01-01T12:00:01+00:00",
             "x": 100, "y": 200, "z": 5}]


class StubClient:
    def __init__(self, sessions=None, laps=None, car=None, loc=None):
        self.sessions = [{"session_key": SK, "session_name": "Qualifying"}] \
            if sessions is None else sessions
        self.laps = laps or {}
        self.car = car or {}
        self.loc = loc or {}

    async def get(self, resource, params):
        if resource == "sessions":
            return self.sessions
        d = params["driver_number"]
        return {"laps": self.laps, "car_data": self.car, "location": self.loc}[resource].get(d, [])


def _happy():
    return StubClient(laps={1: [_lap(1)], 2: [_lap(2)]}, car={1: _car(1), 2: _car(2)},
                      loc={1: _loc(1), 2: _loc(2)})


async def test_happy_path_returns_both_drivers_and_records_queries():
    res = await fetch.acquire_pair(_happy(), SK, [(1, None), (2, None)])
    assert set(res["drivers"]) == {"1", "2"}
    assert [q["endpoint"] for q in res["queries"]] == \
        ["/v1/sessions", "/v1/laps", "/v1/car_data", "/v1/location",
         "/v1/laps", "/v1/car_data", "/v1/location"]
    loc_q = res["queries"][3]["params"]
    assert (loc_q["date>"], loc_q["date<"]) == ("2024-01-01T12:00:00+00:00",
                                                "2024-01-01T12:01:30+00:00")
    car_q = res["queries"][2]["params"]
    # OpenF1 rebuilds each filter as f"{key}={value}" before splitting on the
    # operator (openf1 query_api/query_params.py). A key of "date>=" therefore
    # becomes "date>==<ts>" -> value "=<ts>", a string that matches nothing.
    # The key "date>" becomes "date>=<ts>" - an inclusive, correctly typed
    # filter. Same convention as OpenF1Client._bounds. Verified by running
    # OpenF1's real parser on what httpx sends.
    assert "date>=" not in car_q and "date<=" not in car_q
    assert car_q["date>"] == "2024-01-01T12:00:00+00:00"
    assert car_q["date<"] == "2024-01-01T12:01:30+00:00"  # start + lap_duration


async def test_contaminated_car_data_aborts_instead_of_saving():
    client = _happy()
    client.car[2] = _car(55)  # served another driver's rows
    with pytest.raises(IdentityMismatch):
        await fetch.acquire_pair(client, SK, [(1, None), (2, None)])


async def test_wrong_session_car_data_aborts():
    client = _happy()
    client.car[2] = _car(2, sk=9159)
    with pytest.raises(IdentityMismatch):
        await fetch.acquire_pair(client, SK, [(1, None), (2, None)])


async def test_contaminated_location_aborts():
    client = _happy()
    client.loc[2] = _loc(44)
    with pytest.raises(IdentityMismatch):
        await fetch.acquire_pair(client, SK, [(1, None), (2, None)])


async def test_empty_location_window_aborts():
    client = _happy()
    client.loc[1] = []
    with pytest.raises(OpenF1Error, match="no location"):
        await fetch.acquire_pair(client, SK, [(1, None), (2, None)])


async def test_missing_session_aborts():
    with pytest.raises(OpenF1Error):
        await fetch.acquire_pair(StubClient(sessions=[]), SK, [(1, None), (2, None)])


async def test_empty_telemetry_window_aborts():
    client = _happy()
    client.car[2] = []
    with pytest.raises(OpenF1Error, match="no car_data"):
        await fetch.acquire_pair(client, SK, [(1, None), (2, None)])


async def test_driver_with_only_pit_out_laps_aborts():
    client = _happy()
    client.laps[2] = [_lap(2, pit_out=True)]
    with pytest.raises(OpenF1Error, match="no complete non-pit-out lap"):
        await fetch.acquire_pair(client, SK, [(1, None), (2, None)])


async def test_written_fixture_is_raw_and_carries_provenance(tmp_path):
    res = await fetch.acquire_pair(_happy(), SK, [(1, None), (2, None)])
    fetch.write_fixture(res, tmp_path, lap_length_m=5000.0, lap_length_source="test")
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert (meta["driver_a"], meta["driver_b"], meta["session_key"]) == (1, 2, SK)
    assert meta["lap_length_source"] == "test" and meta["queries"]
    assert json.loads((tmp_path / "driver_2_car_data.json").read_text()) == _car(2)  # unmodified
    assert json.loads((tmp_path / "driver_2_location.json").read_text()) == _loc(2)
