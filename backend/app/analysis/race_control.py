"""Deterministic race-control state + flag-period timeline.

Extends the Phase 1.5 projection with an ordered timeline of interference
periods used by lap classification and pace exclusions:

    [(kind, start_ts, start_lap, end_ts|None), ...]

Kinds: YELLOW | DOUBLE_YELLOW | SAFETY_CAR | VSC | RED_FLAG.
Ordering rule: inputs are sorted by timestamp before folding (spec §15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.session_state import SessionPhase, SessionStateProjection, TrackFlag


@dataclass
class InterferencePeriod:
    kind: str                    # YELLOW|DOUBLE_YELLOW|SAFETY_CAR|VSC|RED_FLAG
    start: datetime
    end: datetime | None = None
    start_lap: int | None = None
    end_lap: int | None = None


@dataclass
class RaceControlState:
    projection: SessionStateProjection = field(default_factory=SessionStateProjection)
    periods: list[InterferencePeriod] = field(default_factory=list)
    _open: dict[str, InterferencePeriod] = field(default_factory=dict)
    last_update: datetime | None = None

    # ---------------------------------------------------------------- fold --

    def fold_rcm(self, ts: datetime | None, message: str, category: str | None,
                 flag: str | None, lap_number: int | None = None) -> None:
        self.last_update = max(self.last_update, ts) if self.last_update and ts else (
            ts or self.last_update
        )
        self.projection.fold_rcm(message, category, flag, ts)
        msg_u = (message or "").upper()

        def open_period(kind: str) -> None:
            if kind in self._open:
                return
            p = InterferencePeriod(kind=kind, start=ts or datetime.now(tz=None),
                                   start_lap=lap_number)
            self._open[kind] = p

        def close_period(kind: str) -> None:
            p = self._open.pop(kind, None)
            if p is not None:
                p.end = ts
                p.end_lap = lap_number
                self.periods.append(p)

        if flag == "YELLOW":
            open_period("YELLOW")
        elif flag == "DOUBLE YELLOW":
            close_period("YELLOW")
            open_period("DOUBLE_YELLOW")
        elif flag == "CLEAR" or flag == "GREEN":
            close_period("YELLOW")
            close_period("DOUBLE_YELLOW")
        elif "SAFETY CAR DEPLOYED" in msg_u:
            open_period("SAFETY_CAR")
        elif "SAFETY CAR IN THIS LAP" in msg_u or "SAFETY CAR ENDING" in msg_u:
            close_period("SAFETY_CAR")
        elif "VSC DEPLOYED" in msg_u or "VIRTUAL SAFETY CAR DEPLOYED" in msg_u:
            open_period("VSC")
        elif "VSC ENDING" in msg_u or "VIRTUAL SAFETY CAR ENDING" in msg_u:
            close_period("VSC")
        elif flag == "RED":
            for kind in list(self._open):
                close_period(kind)
            open_period("RED_FLAG")
        elif flag == "CHEQUERED":
            for kind in list(self._open):
                close_period(kind)

    def close_all(self, ts: datetime) -> None:
        for kind in list(self._open):
            p = self._open.pop(kind)
            p.end = ts
            self.periods.append(p)

    # ------------------------------------------------------------- queries --

    def flags_during(self, start: datetime, end: datetime) -> set[str]:
        """Flag kinds active at ANY point during [start, end]."""
        out: set[str] = set()
        for p in self.periods + list(self._open.values()):
            p_start = p.start
            p_end = p.end or datetime.max.replace(tzinfo=p.start.tzinfo)
            if p_start <= end and p_end >= start:
                out.add(p.kind)
        return out

    def phase(self) -> SessionPhase:
        return self.projection.phase

    def track_flag(self) -> TrackFlag:
        return self.projection.track_flag
