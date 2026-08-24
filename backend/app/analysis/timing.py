"""Timing engine (Phase 2): positions, laps, PB/SB tracking, gap evolution.

Deterministic incremental state per driver. Symbolic gaps ('+1 LAP') are
stored verbatim and NEVER converted to seconds (Phase-1 verified upstream).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import DerivedProvenance, Confidence


@dataclass
class DriverTimingState:
    driver_number: int
    position: int | None = None
    previous_position: int | None = None
    lap_number: int | None = None            # latest completed lap
    last_lap_s: float | None = None
    previous_lap_s: float | None = None
    personal_best_s: float | None = None     # valid laps only
    personal_best_lap_number: int | None = None
    gap_to_leader_raw: str | None = None     # '+1 LAP' preserved here too
    gap_to_leader_s: float | None = None     # numeric only; None when symbolic
    interval_raw: str | None = None
    interval_s: float | None = None
    in_pit: bool = False
    retired: bool = False
    # gap evolution: (lap_number, gap_to_leader_s) numeric samples only
    gap_history: list[tuple[int | None, float]] = field(default_factory=list)


@dataclass
class SessionTimingState:
    session_id: str
    drivers: dict[int, DriverTimingState] = field(default_factory=dict)
    session_best_s: float | None = None
    session_best_driver: int | None = None
    fastest_lap_changed_at_lap: int | None = None

    def driver(self, num: int) -> DriverTimingState:
        if num not in self.drivers:
            self.drivers[num] = DriverTimingState(driver_number=num)
        return self.drivers[num]


class TimingEngine:
    """Folds canonical Lap / PositionUpdate / TimingInterval facts."""

    def __init__(self, session_id: str) -> None:
        self.state = SessionTimingState(session_id=session_id)

    # ---------------------------------------------------------------- lap ----

    def fold_lap(self, *, driver_number: int, lap_number: int,
                 duration_s: float | None, deleted: bool,
                 provenance: DerivedProvenance | None = None) -> dict | None:
        d = self.state.driver(driver_number)
        d.lap_number = max(d.lap_number or 0, lap_number)
        if deleted:
            # tombstone: retract from personal best if it was the holder
            if d.personal_best_lap_number == lap_number:
                d.personal_best_s = None
                d.personal_best_lap_number = None
            return {"retracted": True}
        if duration_s is None:
            return None
        d.previous_lap_s = d.last_lap_s
        d.last_lap_s = duration_s
        pb_update = False
        if d.personal_best_s is None or duration_s < d.personal_best_s:
            d.personal_best_s = duration_s
            d.personal_best_lap_number = lap_number
            pb_update = True
        sb_update = False
        if self.state.session_best_s is None or duration_s < self.state.session_best_s:
            prev_holder = self.state.session_best_driver
            self.state.session_best_s = duration_s
            self.state.session_best_driver = driver_number
            self.state.fastest_lap_changed_at_lap = lap_number
            sb_update = prev_holder is not None  # first-ever SB isn't a "change"
        return {"personal_best": pb_update, "session_best": sb_update}

    # ------------------------------------------------------------ position --

    def fold_position(self, driver_number: int, ts, new_position: int) -> int | None:
        """Apply an authoritative position change; returns delta or None."""
        d = self.state.driver(driver_number)
        old = d.position
        if old == new_position:
            return None
        d.previous_position = old
        d.position = new_position
        return (old - new_position) if old is not None else None

    def recompute_positions_from_gaps(self) -> list[tuple[int, int, int]]:
        """Deterministic ordering fallback: sort by numeric gap then number.
        Returns [(driver, old_pos, new_pos)] for changed rows."""
        with_gap = [(n, d.gap_to_leader_s) for n, d in self.state.drivers.items()
                    if d.gap_to_leader_s is not None and not d.retired]
        without = [n for n, d in self.state.drivers.items()
                   if d.gap_to_leader_s is None and not d.retired]
        ordered = [n for n, _ in sorted(with_gap, key=lambda t: t[1])] + sorted(without)
        changes = []
        for idx, num in enumerate(ordered, start=1):
            d = self.state.driver(num)
            old = d.position
            if old != idx:
                d.previous_position = old
                d.position = idx
                changes.append((num, old, idx))
        return changes

    # --------------------------------------------------------------- gaps ----

    @staticmethod
    def apply_interval_sample(d: DriverTimingState, gap_raw: object,
                              interval_raw: object, lap: int | None) -> None:
        """Store raw + numeric. Symbolic strings never become numbers."""
        if gap_raw is not None:
            if isinstance(gap_raw, (int, float)):
                d.gap_to_leader_s = float(gap_raw)
                d.gap_history.append((lap, float(gap_raw)))
            else:
                d.gap_to_leader_raw = str(gap_raw)
                d.gap_to_leader_s = None
        elif isinstance(gap_raw, str):
            d.gap_to_leader_raw = gap_raw
        if isinstance(interval_raw, (int, float)):
            d.interval_s = float(interval_raw)
            d.interval_raw = None
        elif interval_raw is not None:
            d.interval_raw = str(interval_raw)
            d.interval_s = None

    def mark_pit(self, driver_number: int, in_pit: bool) -> None:
        self.state.driver(driver_number).in_pit = in_pit

    def mark_retired(self, driver_number: int) -> None:
        d = self.state.driver(driver_number)
        d.retired = True
        d.in_pit = False
