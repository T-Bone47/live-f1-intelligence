"""Session snapshot (Phase 2): deterministic projection for Phase-3 delivery.

Rebuildable at any time by folding the same canonical events; identical input
=> identical snapshot (determinism contract, verified in backtests).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.battles import BattleDetector
from app.analysis.common.models import CleanAir
from app.analysis.gaps import GapEngine
from app.analysis.pace import PaceEngine
from app.analysis.race_control import RaceControlState
from app.analysis.sectors import SectorEngine
from app.analysis.timing import TimingEngine
from app.analysis.tyres import StintEngine
from app.analysis.weather import WeatherEngine


@dataclass
class LeaderboardRow:
    position: int | None
    driver_number: int
    lap_number: int | None = None
    last_lap_s: float | None = None
    personal_best_s: float | None = None
    gap_to_leader_raw: str | None = None     # '+1 LAP' preserved verbatim
    gap_to_leader_s: float | None = None
    interval_s: float | None = None
    compound: str | None = None
    tyre_age: int | None = None
    stint_number: int | None = None
    rolling5_s: float | None = None
    pace_trend_s_per_lap: float | None = None
    clean_air: str | None = None             # TRUE/FALSE/UNKNOWN/None(no gaps)
    in_pit: bool = False
    retired: bool = False


@dataclass
class SessionSnapshot:
    session_id: str
    phase: str
    track_flag: str
    current_lap: int | None
    leaderboard: list[LeaderboardRow] = field(default_factory=list)
    fastest_lap: dict | None = None
    sector_leaders: dict[int, tuple[float, int]] = field(default_factory=dict)
    active_battles: list[dict] = field(default_factory=list)
    weather: dict = field(default_factory=dict)
    recent_events: list[dict] = field(default_factory=list)


class SnapshotBuilder:
    def __init__(self, *, timing: TimingEngine, sectors: SectorEngine,
                 pace: PaceEngine, stints: StintEngine, gaps: GapEngine,
                 battles: BattleDetector, rc: RaceControlState,
                 weather: WeatherEngine) -> None:
        self.timing = timing
        self.sectors = sectors
        self.pace = pace
        self.stints = stints
        self.gaps = gaps
        self.battles = battles
        self.rc = rc
        self.weather = weather

    def build(self, recent_events: list[dict]) -> SessionSnapshot:
        tstate = self.timing.state
        positions = {n: d.position or 0 for n, d in tstate.drivers.items()}
        neighbors = self.gaps.neighbors_by_position(positions)

        rows: list[LeaderboardRow] = []
        for num, d in sorted(tstate.drivers.items(), key=lambda kv:
                             (kv[1].position is None, kv[1].position or 999)):
            ahead_n, behind_n = neighbors.get(num, (None, None))
            gap_ahead = d.interval_s if d.interval_s is not None else None
            gap_behind = None
            if behind_n is not None:
                gap_behind = tstate.drivers[behind_n].interval_s
            clean = PaceEngine.classify_clean_air(
                gap_ahead, gap_behind, is_leader=(d.position == 1))
            stint = self.stints.current(num)
            rows.append(LeaderboardRow(
                position=d.position,
                driver_number=num,
                lap_number=d.lap_number,
                last_lap_s=d.last_lap_s,
                personal_best_s=d.personal_best_s,
                gap_to_leader_raw=d.gap_to_leader_raw,
                gap_to_leader_s=d.gap_to_leader_s,
                interval_s=d.interval_s,
                compound=stint.compound.value if stint else None,
                tyre_age=self.stints.tyre_age(num, d.lap_number),
                stint_number=stint.stint_number if stint else None,
                rolling5_s=self.pace.rolling_pace(num, 5),
                pace_trend_s_per_lap=self.pace.pace_trend(num),
                clean_air=(clean.value if clean is not CleanAir.UNKNOWN
                           else CleanAir.UNKNOWN.value),
                in_pit=d.in_pit,
                retired=d.retired,
            ))

        fl = None
        if tstate.session_best_s is not None:
            fl = {"driver": tstate.session_best_driver,
                  "duration_s": tstate.session_best_s,
                  "at_lap": tstate.fastest_lap_changed_at_lap}

        battles = [
            {"ahead": b.ahead, "behind": b.behind, "state": b.state.value,
             "min_gap_s": b.min_gap_s, "last_gap_s": b.last_gap_s,
             "started_lap": b.started_lap}
            for b in self.battles.active_battles()
            if b.state.value != "APPROACHING"
        ]

        return SessionSnapshot(
            session_id=tstate.session_id,
            phase=self.rc.phase().value,
            track_flag=self.rc.track_flag().value,
            current_lap=max((d.lap_number or 0) for d in tstate.drivers.values())
            if tstate.drivers else None,
            leaderboard=rows,
            fastest_lap=fl,
            sector_leaders=self.sectors.session_best_holders(),
            active_battles=battles,
            weather=self.weather.latest(),
            recent_events=recent_events[-25:],
        )

    def to_dict(self, snap: SessionSnapshot) -> dict:
        return {
            "session_id": snap.session_id,
            "phase": snap.phase,
            "track_flag": snap.track_flag,
            "current_lap": snap.current_lap,
            "fastest_lap": snap.fastest_lap,
            "sector_leaders": {
                f"S{k}": {"time_s": v[0], "driver": v[1]}
                for k, v in snap.sector_leaders.items()},
            "weather": snap.weather,
            "active_battles": snap.active_battles,
            "recent_events": snap.recent_events,
            "leaderboard": [
                {k: getattr(r, k) for k in r.__dataclass_fields__}
                for r in snap.leaderboard
            ],
        }
