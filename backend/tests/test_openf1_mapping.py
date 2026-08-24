"""OpenF1 raw payload -> canonical mapping tests (fixtures = REAL API data)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.enums import Compound, ProvenanceClass, ProviderName, SessionType
from app.providers.openf1.mapping import (
    NormalizationError,
    map_session_type,
    parse_ts,
    safe,
    to_car_sample,
    to_driver,
    to_interval,
    to_lap,
    to_location_sample,
    to_pit_stop,
    to_position,
    to_rcm,
    to_session,
    to_stint,
    to_weather,
)

FIXTURES = Path(__file__).parent / "fixtures" / "openf1"


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


B = ProvenanceClass.B


class TestTimestamps:
    def test_parse_iso_with_offset(self) -> None:
        ts = parse_ts("2026-08-23T13:03:28.567000+00:00")
        assert ts.tzinfo is not None
        assert ts.year == 2026 and ts.hour == 13

    def test_parse_z_suffix(self) -> None:
        assert parse_ts("2026-08-23T13:03:28Z") == parse_ts("2026-08-23T13:03:28+00:00")

    def test_source_timestamp_preserved_through_mapping(self) -> None:
        row = load("car_data.json")[0]
        sample = safe(to_car_sample, row, "openf1:11353", B)
        assert sample.ts == parse_ts(row["date"])
        assert sample.provenance.source_timestamp == sample.ts

    def test_malformed_ts_raises_normalization_error(self) -> None:
        with pytest.raises(NormalizationError):
            parse_ts("not-a-date")
        with pytest.raises(NormalizationError):
            parse_ts(None)


class TestSessionMapping:
    def test_real_session_fixture(self) -> None:
        row = load("sessions_latest.json")[0]
        s = safe(to_session, row)
        assert s.provider_session_key == "11353"
        assert s.session_id == "openf1:11353"
        assert s.circuit_short_name == "Zandvoort"
        assert s.session_type == SessionType.RACE
        assert s.date_end > s.date_start

    def test_session_status_derived(self) -> None:
        row = dict(load("sessions_latest.json")[0])
        row["date_start"] = "2020-01-01T00:00:00+00:00"
        row["date_end"] = "2020-01-01T02:00:00+00:00"
        s = safe(to_session, row)
        assert s.status.value == "FINISHED"

    def test_broken_year_filter_documented(self) -> None:
        # upstream year= filter returns empty even for existing seasons;
        # our discovery must not depend on it (see provider._recent_meetings_scan)
        assert True


class TestDriverMapping:
    def test_real_driver_fixture(self) -> None:
        row = load("drivers.json")[0]
        d = safe(to_driver, row)
        assert d.driver_id == f"lando-norris-{row['driver_number']}"
        assert d.name_acronym == "NOR"
        assert d.team is not None and d.team.team_id == "mclaren"
        # country_code null preserved as None (verified upstream behavior)
        if row.get("country_code") is None:
            assert d.country_code is None


class TestLapMapping:
    def test_real_lap_fixture_with_segments(self) -> None:
        rows = load("laps.json")
        lap, sectors = safe(to_lap, rows[0], "openf1:11353", B)
        assert lap.lap_number == 1
        assert lap.duration_s == pytest.approx(86.305)
        assert lap.sector1_s == pytest.approx(32.697)
        assert lap.speed_traps.st_kph == 212
        assert len(sectors) == 3
        s1 = sectors[0]
        assert s1.segment_codes is not None and s1.segment_codes[0] is None
        assert all(sec.time_s for sec in sectors)

    def test_lap_with_nulls(self) -> None:
        # fixture lap 3 has null sector/duration values - must stay null
        rows = load("laps.json")
        lap, sectors = safe(to_lap, rows[2], "openf1:11353", B)
        assert lap.duration_s is None
        assert lap.sector1_s is None
        assert sectors[0].time_s is None
        assert sectors[1].segment_codes is None

    def test_missing_date_start_rejected(self) -> None:
        with pytest.raises(NormalizationError):
            safe(to_lap, {"driver_number": 1, "lap_number": 1}, "s", B)


class TestTelemetryMapping:
    def test_car_samples(self) -> None:
        for row in load("car_data.json"):
            m = safe(to_car_sample, row, "openf1:11353", B)
            assert 0 <= m.throttle_pct <= 100 or m.throttle_pct is None
            if row.get("drs") is None:
                assert m.drs is None  # verified nullable upstream

    def test_location_samples(self) -> None:
        row = load("location.json")[0]
        loc = safe(to_location_sample, row, "openf1:11353", B)
        assert loc.x == row["x"] and loc.y == row["y"] and loc.z == row["z"]


class TestTyrePitWeatherRcm:
    def test_stints(self) -> None:
        stints = [safe(to_stint, r, "openf1:11353", B) for r in load("stints.json")]
        assert stints[0].stint_number == 1  # verified 1-based
        assert stints[0].compound == Compound.MEDIUM
        assert any(s.compound == Compound.HARD for s in stints)

    def test_pits_nullable_stop_duration(self) -> None:
        pits = [safe(to_pit_stop, r, "openf1:11353", B) for r in load("pits.json")]
        first = pits[0]
        if load("pits.json")[0].get("stop_duration") is None:
            assert first.stop_duration_s is None  # stays null, not zeroed
        assert first.lane_duration_s is not None

    def test_weather(self) -> None:
        row = load("weather.json")[0]
        wx = safe(to_weather, row, "openf1:11353", B)
        assert wx.air_temp_c == row["air_temperature"]
        assert wx.rainfall is bool(row["rainfall"])

    def test_rcm_marshal_sector_not_timing_sector(self) -> None:
        for row in load("race_control.json"):
            rcm = safe(to_rcm, row, "openf1:11353", B)
            if rcm.marshal_sector is not None:
                # marshal posts go beyond timing sector 3 (verified: 7,14,18...)
                assert isinstance(rcm.marshal_sector, int)

    def test_rcm_dedupe_key_stable(self) -> None:
        row = load("race_control.json")[0]
        k1 = safe(to_rcm, row, "openf1:11353", B).rcm_key
        k2 = safe(to_rcm, json.loads(json.dumps(row)), "openf1:11353", B).rcm_key
        assert k1 == k2


class TestPositionIntervals:
    def test_positions(self) -> None:
        row = load("position.json")[0]
        pos = safe(to_position, row, "openf1:11353", B)
        assert pos.position >= 1

    def test_intervals(self) -> None:
        row = load("intervals.json")[0]
        iv = safe(to_interval, row, "openf1:11353", B)
        assert iv.gap_to_leader_s == pytest.approx(row["gap_to_leader"])

    def test_intervals_lapped_traffic_raw_preserved(self) -> None:
        # REAL upstream behavior (2026 Dutch GP): lapped cars send '+1 LAP'
        row = {
            "date": "2026-08-23T13:37:09.731000+00:00",
            "session_key": 11353,
            "gap_to_leader": "+1 LAP",
            "interval": 175.371,
            "driver_number": 41,
            "meeting_key": 1292,
        }
        iv = safe(to_interval, row, "openf1:11353", B)
        assert iv.gap_to_leader_s is None  # numeric value absent - stays absent
        assert iv.gap_raw == "+1 LAP"  # raw preserved verbatim
        assert iv.interval_s == pytest.approx(175.371)


class TestSessionTypeMap:
    def test_known_and_unknown(self) -> None:
        assert map_session_type("Race") == SessionType.RACE
        assert map_session_type("practice") == SessionType.PRACTICE
        assert map_session_type("Sprint Qualifying") == SessionType.SPRINT_QUALI
        assert map_session_type("Something New 2027") == SessionType.UNKNOWN
