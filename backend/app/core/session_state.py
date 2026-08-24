"""Canonical session-state projection.

Folds canonical events (RCM messages, session metadata, lap counts) into a
single authoritative phase. This state later drives the live frontend and AI;
it uses ONLY verified upstream signals - never guesses.

Phases (Phase 1.5 contract):
SCHEDULED | FORMATION | LIVE | SUSPENDED | RED_FLAG | SAFETY_CAR | VSC |
CHEQUERED | FINISHED | UNKNOWN

VERIFIED upstream triggers (OpenF1 RCM texts, 2026 Dutch GP):
- "GREEN LIGHT - PIT EXIT OPEN"          (Flag/GREEN)
- "YELLOW IN TRACK SECTOR n"             (Flag/YELLOW)
- "DOUBLE YELLOW IN TRACK SECTOR n"      (Flag/DOUBLE YELLOW)
- "CLEAR IN TRACK SECTOR n"              (Flag/CLEAR)
- "RED FLAG"                             (Flag/RED)
- "CHEQUERED FLAG"                       (Flag/CHEQUERED)
- "SAFETY CAR DEPLOYED"                  (SafetyCar category)
- "SAFETY CAR IN THIS LAP"               (SafetyCar)
- "VSC DEPLOYED" / "VIRTUAL SAFETY CAR DEPLOYED"
- "VSC ENDING" / "VIRTUAL SAFETY CAR ENDING"
Assumed-but-unverified variants are matched conservatively (see PATTERNS).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SessionPhase(str, Enum):
    SCHEDULED = "SCHEDULED"
    FORMATION = "FORMATION"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    RED_FLAG = "RED_FLAG"
    SAFETY_CAR = "SAFETY_CAR"
    VSC = "VSC"
    CHEQUERED = "CHEQUERED"
    FINISHED = "FINISHED"
    UNKNOWN = "UNKNOWN"


class TrackFlag(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    DOUBLE_YELLOW = "DOUBLE_YELLOW"
    CLEAR = "CLEAR"
    RED = "RED"
    CHEQUERED = "CHEQUERED"
    UNKNOWN = "UNKNOWN"


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bRED FLAG\b", re.I), "red"),
    (re.compile(r"\bCHEQUERED FLAG\b", re.I), "chequered"),
    (re.compile(r"\b(VIRTUAL\s+)?SAFETY CAR\s+DEPLOYED\b|\bVSC DEPLOYED\b", re.I), "vsc_or_sc"),
    (re.compile(r"\b(VIRTUAL\s+)?SAFETY CAR (IN THIS LAP|ENDING)\b|\bVSC ENDING\b", re.I), "sc_ending"),
    (re.compile(r"\bGREEN LIGHT\b|\bTRACK CLEAR\b|\bGREEN FLAG\b", re.I), "green"),
    (re.compile(r"\bDOUBLE YELLOW\b", re.I), "double_yellow"),
    (re.compile(r"\bYELLOW\b", re.I), "yellow"),
    (re.compile(r"\bCLEAR\b", re.I), "clear"),
]

# Category values observed upstream: Flag, Other, SessionStatus, SafetyCar
_SAFETYCAR_CATEGORY = {"safetycar", "safety car"}


@dataclass
class StateTransition:
    ts: datetime | None
    from_phase: SessionPhase
    to_phase: SessionPhase
    trigger: str


@dataclass
class SessionStateProjection:
    phase: SessionPhase = SessionPhase.UNKNOWN
    track_flag: TrackFlag = TrackFlag.UNKNOWN
    lap_count: int | None = None
    last_rcm_ts: datetime | None = None
    history: list[StateTransition] = field(default_factory=list)

    def _transition(self, to: SessionPhase, ts: datetime | None, trigger: str) -> None:
        if to is not self.phase:
            self.history.append(
                StateTransition(ts=ts, from_phase=self.phase, to_phase=to, trigger=trigger[:120])
            )
            self.phase = to

    # ------------------------------------------------------------- folds ----

    def fold_session_window(self, date_start: datetime | None, date_end: datetime | None,
                            now: datetime) -> None:
        """Schedule-derived fallback phase (weakest signal; RCM overrides)."""
        if date_start is None or date_end is None or self.phase is not SessionPhase.UNKNOWN:
            return
        if now < date_start:
            self._transition(SessionPhase.SCHEDULED, None, "session window: before start")
        elif now <= date_end:
            self._transition(SessionPhase.LIVE, None, "session window: within")
        else:
            self._transition(SessionPhase.FINISHED, None, "session window: after end")

    def fold_rcm(self, message: str, category: str | None, flag: str | None,
                 ts: datetime | None) -> None:
        self.last_rcm_ts = ts or self.last_rcm_ts
        cat = (category or "").strip().lower()
        flag_u = (flag or "").strip().upper()

        # 1) explicit red / chequered dominate everything
        if flag_u == "RED" or re.search(r"\bRED FLAG\b", message or "", re.I):
            self.track_flag = TrackFlag.RED
            self._transition(SessionPhase.RED_FLAG, ts, f"rcm:{message}")
            return
        if flag_u == "CHEQUERED" or re.search(r"\bCHEQUERED FLAG\b", message or "", re.I):
            self.track_flag = TrackFlag.CHEQUERED
            self._transition(SessionPhase.CHEQUERED, ts, f"rcm:{message}")
            return

        # 2) safety car / vsc by category first (verified category 'SafetyCar')
        if cat in {c.lower() for c in _SAFETYCAR_CATEGORY}:
            if re.search(r"IN THIS LAP|ENDING", message or "", re.I):
                self._transition(SessionPhase.LIVE, ts, f"rcm(sc ending):{message}")
            else:
                self._transition(SessionPhase.SAFETY_CAR, ts, f"rcm(sc):{message}")
            return
        m = re.search(r"\bVSC DEPLOYED\b|\bVIRTUAL SAFETY CAR DEPLOYED\b", message or "", re.I)
        if m:
            self._transition(SessionPhase.VSC, ts, f"rcm:{message}")
            return
        if re.search(r"\bVSC ENDING\b|\bVIRTUAL SAFETY CAR ENDING\b", message or "", re.I):
            self._transition(SessionPhase.LIVE, ts, f"rcm(vsc ending):{message}")
            return

        # 3) flags
        if flag_u == "GREEN":
            self.track_flag = TrackFlag.GREEN
            if self.phase in (SessionPhase.UNKNOWN, SessionPhase.SCHEDULED,
                              SessionPhase.FORMATION):
                self._transition(SessionPhase.LIVE, ts, f"rcm:{message}")
            return
        if flag_u == "CLEAR":
            self.track_flag = TrackFlag.CLEAR
            if self.phase in (SessionPhase.RED_FLAG,):
                self._transition(SessionPhase.LIVE, ts, f"rcm:{message}")
            return
        if flag_u == "YELLOW":
            self.track_flag = TrackFlag.YELLOW
            if self.phase is SessionPhase.UNKNOWN:
                self._transition(SessionPhase.LIVE, ts, f"rcm:{message}")
            return
        if flag_u == "DOUBLE YELLOW":
            self.track_flag = TrackFlag.DOUBLE_YELLOW
            if self.phase is SessionPhase.UNKNOWN:
                self._transition(SessionPhase.LIVE, ts, f"rcm:{message}")
            return

        # 4) session status category (observed upstream: 'SessionStatus')
        if cat == "sessionstatus":
            mu = (message or "").upper()
            if "FINISHED" in mu:
                self._transition(SessionPhase.FINISHED, ts, f"rcm(status):{message}")
            elif "STARTED" in mu or "BEGIN" in mu:
                self._transition(SessionPhase.LIVE, ts, f"rcm(status):{message}")
            elif "SUSPENDED" in mu:
                self._transition(SessionPhase.SUSPENDED, ts, f"rcm(status):{message}")

    def fold_lap_count(self, current: int) -> None:
        self.lap_count = current

    def apply(self, rcm_rows: list[dict]) -> "SessionStateProjection":
        """Fold raw-ish RCM dicts ({date, category, flag, message}) in order."""
        for row in sorted(rcm_rows, key=lambda r: str(r.get("date", ""))):
            ts_raw = row.get("date")
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else None
            self.fold_rcm(row.get("message") or "", row.get("category"),
                          row.get("flag"), ts)
        return self


def project_from_rcm(rcm_rows: list[dict]) -> SessionStateProjection:
    """Convenience: build projection purely from an ordered RCM list."""
    return SessionStateProjection().apply(rcm_rows)
