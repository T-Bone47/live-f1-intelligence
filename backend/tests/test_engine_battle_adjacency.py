"""AnalysisEngine battle adjacency (Phase 11).

Real finding (2026 Dutch GP race, lap 40): the snapshot listed 84 "active
battles" for 22 cars, and only 4 were between cars that were adjacent at that
moment. BattleDetector keeps one state per (ahead, behind) pair and only the
current neighbour pair is ever updated, so a pair that stopped being adjacent
kept its last state (ACTIVE_BATTLE, DEFENDING...) forever. Separately, cars
with no reported position were treated as position 0, i.e. "ahead of" P1.

A battle is between adjacent cars: a pair ends when the cars stop being
neighbours, and a car without a position is nobody's neighbour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.analysis import AnalysisEngine
from app.core.events import Envelope

T0 = datetime(2026, 8, 23, 14, 0, 0, tzinfo=UTC)
PROV = {"provider": "openf1", "provenance_class": "B"}


def _env(mtype: str, data: dict, ts: datetime) -> Envelope:
    return Envelope(event_type="x", session_id="s", source="test",
                    source_timestamp=ts, ingestion_timestamp=T0,
                    provenance_class="B", payload={"model": {"type": mtype, **data}})


class Race:
    def __init__(self) -> None:
        self.e = AnalysisEngine("s")
        self.e.flush_deferred()
        self.t = T0

    def _tick(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t

    def position(self, driver: int, pos: int) -> None:
        ts = self._tick()
        self.e.process_envelope(_env("PositionUpdate", {
            "session_id": "s", "driver_number": driver, "ts": ts.isoformat(),
            "position": pos, "provenance": PROV}, ts))

    def interval(self, driver: int, gap: float) -> None:
        ts = self._tick()
        self.e.process_envelope(_env("TimingInterval", {
            "session_id": "s", "driver_number": driver, "ts": ts.isoformat(),
            "gap_to_leader_s": None, "gap_raw": None, "interval_s": gap,
            "provenance": PROV}, ts))

    def pairs(self) -> set[tuple[int, int]]:
        return {(b["ahead"], b["behind"]) for b in self.e.snapshot_dict()["active_battles"]}


def test_pair_that_stops_being_adjacent_is_not_reported():
    r = Race()
    for d, p in ((10, 1), (20, 2), (30, 3)):
        r.position(d, p)
    r.interval(20, 0.5)
    r.interval(20, 0.4)
    assert (10, 20) in r.pairs()
    # 30 passes 20: order is now 10, 30, 20
    r.position(30, 2)
    r.position(20, 3)
    r.interval(30, 0.4)
    r.interval(20, 0.3)
    assert (10, 20) not in r.pairs()
    assert r.pairs() <= {(10, 30), (30, 20)}


def test_a_pair_that_becomes_adjacent_again_starts_fresh():
    r = Race()
    for d, p in ((10, 1), (20, 2), (30, 3)):
        r.position(d, p)
    r.interval(20, 0.2)                      # min gap 0.2 while adjacent
    r.position(30, 2)
    r.position(20, 3)
    r.interval(20, 0.9)                      # 20 now behind 30
    r.position(20, 2)
    r.position(30, 3)
    r.interval(20, 1.5)                      # back behind 10
    b = r.e.battles.battles.get((10, 20))
    assert b is not None and b.min_gap_s == 1.5


def test_a_car_without_a_position_is_nobodys_neighbour():
    r = Race()
    r.position(10, 1)
    r.position(20, 2)
    r.interval(99, 0.3)                      # car 99 has no position at all
    r.interval(10, 0.5)                      # the leader has nobody ahead of it
    r.interval(10, 0.4)
    r.interval(20, 0.5)
    r.interval(20, 0.4)
    assert r.pairs() == {(10, 20)}


def test_a_car_without_a_position_never_enters_a_pair_state():
    r = Race()
    r.position(10, 1)
    r.interval(99, 0.3)                      # car 99 has no position at all
    r.interval(10, 0.4)
    assert (99, 10) not in r.e.battles.battles


def test_snapshot_drops_a_pair_whose_behind_car_has_not_reported_since():
    # a car that stops sending intervals (e.g. retired) never re-pairs itself,
    # so the snapshot must check adjacency at the moment it is built
    r = Race()
    for d, p in ((10, 1), (20, 2), (30, 3)):
        r.position(d, p)
    r.interval(20, 0.5)
    r.interval(20, 0.4)
    r.position(30, 2)                        # 30 now between 10 and 20 ...
    r.position(20, 3)                        # ... and 20 sends nothing more
    assert (10, 20) not in r.pairs()
