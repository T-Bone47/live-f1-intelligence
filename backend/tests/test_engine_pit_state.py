"""AnalysisEngine pit state (Phase 11).

`in_pit` used to be set by a PitStop and never cleared, so after a driver's
first stop the leaderboard showed PIT for the rest of the race and the battle
detector treated the car as "pitted or out" forever.

Rule (from the real 2026 Dutch GP rows): a stop's `lap_number` is the in-lap;
the car is back on track once it completes any later lap (the out-lap).
Without a stop lap number, the first lap that starts at/after the stop and
completes clears it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.analysis import AnalysisEngine
from app.core.events import Envelope

T0 = datetime(2026, 8, 23, 14, 0, 0, tzinfo=UTC)
PROV = {"provider": "openf1", "provenance_class": "B"}


def _env(mtype: str, data: dict, ts: datetime | None) -> Envelope:
    return Envelope(event_type="x", session_id="s", source="test",
                    source_timestamp=ts, ingestion_timestamp=T0,
                    provenance_class="B", payload={"model": {"type": mtype, **data}})


def lap(driver: int, n: int, start: datetime, dur: float | None) -> Envelope:
    return _env("Lap", {
        "session_id": "s", "driver_number": driver, "lap_number": n,
        "started_at": start.isoformat(), "duration_s": dur,
        "sector1_s": None, "sector2_s": None, "sector3_s": None,
        "is_pit_out_lap": False, "deleted": False,
        "speed_traps": {"i1_kph": None, "i2_kph": None, "st_kph": None},
        "provenance": PROV}, start)


def pit(driver: int, ts: datetime, lap_number: int | None) -> Envelope:
    return _env("PitStop", {
        "session_id": "s", "driver_number": driver, "ts": ts.isoformat(),
        "lap_number": lap_number, "lane_duration_s": 18.0, "stop_duration_s": None,
        "provenance": PROV}, ts)


def engine() -> AnalysisEngine:
    e = AnalysisEngine("s")
    e.flush_deferred()  # primed: laps are dispatched immediately
    return e


def in_pit(e: AnalysisEngine, driver: int) -> bool:
    return e.timing.state.driver(driver).in_pit


def test_pit_sets_in_pit_and_the_in_lap_does_not_clear_it():
    e = engine()
    e.process_envelope(lap(1, 20, T0, 80.0))
    e.process_envelope(pit(1, T0 + timedelta(seconds=97), 21))
    assert in_pit(e, 1) is True
    # the in-lap itself (lap 21) completing does not end the stop
    e.process_envelope(lap(1, 21, T0 + timedelta(seconds=80), 80.6))
    assert in_pit(e, 1) is True


def test_completing_the_out_lap_clears_in_pit():
    e = engine()
    e.process_envelope(pit(1, T0 + timedelta(seconds=97), 21))
    e.process_envelope(lap(1, 22, T0 + timedelta(seconds=81), 93.3))
    assert in_pit(e, 1) is False


def test_out_lap_still_running_keeps_in_pit():
    e = engine()
    e.process_envelope(pit(1, T0 + timedelta(seconds=97), 21))
    e.process_envelope(lap(1, 22, T0 + timedelta(seconds=81), None))  # no duration yet
    assert in_pit(e, 1) is True


def test_stop_delivered_after_the_out_lap_does_not_mark_the_car_in_the_pits():
    e = engine()
    e.process_envelope(lap(1, 22, T0 + timedelta(seconds=81), 93.3))
    e.process_envelope(pit(1, T0 + timedelta(seconds=97), 21))
    assert in_pit(e, 1) is False


def test_without_a_stop_lap_number_the_next_lap_started_after_the_stop_clears_it():
    e = engine()
    e.process_envelope(pit(1, T0, None))
    e.process_envelope(lap(1, 21, T0 - timedelta(seconds=60), 80.0))  # started before
    assert in_pit(e, 1) is True
    e.process_envelope(lap(1, 22, T0 + timedelta(seconds=5), 90.0))
    assert in_pit(e, 1) is False


def test_other_drivers_are_unaffected():
    e = engine()
    e.process_envelope(pit(1, T0, 21))
    e.process_envelope(lap(4, 22, T0 + timedelta(seconds=5), 90.0))
    assert in_pit(e, 1) is True and in_pit(e, 4) is False
