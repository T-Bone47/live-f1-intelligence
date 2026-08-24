"""Deterministic battle detection (Phase 2) - BATTLE_DETECTION.md normative.

State machine per ordered pair (ahead A, behind B):

    NO_BATTLE -> APPROACHING   gap <= APPROACH_GAP (2.0 s) and closing
              -> DRS_RANGE     gap <= DRS_GAP (1.0 s)
              -> ACTIVE_BATTLE gap <= ACTIVE_GAP (0.6 s) for >= CONFIRM_SAMPLES (2)
    ACTIVE_BATTLE -> OVERTAKE   position swap within the pair
                  -> DEFENDING   gap re-grows above ACTIVE_GAP while < DRS_GAP
                  -> SEPARATING  gap > SEPARATE_GAP (2.5 s) rising
    any state   -> NO_BATTLE    gap > RESET_GAP (3.0 s) for RESET_SAMPLES (3),
                                or either car pits/retires

All thresholds are module constants; no ML, no probability. Lapped-car pairs
(symbolic gaps) never enter the machine - documented limitation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

APPROACH_GAP = 2.0
DRS_GAP = 1.0
ACTIVE_GAP = 0.6
SEPARATE_GAP = 2.5
RESET_GAP = 3.0
CONFIRM_SAMPLES = 2
RESET_SAMPLES = 3


class BattleState(str, Enum):
    NO_BATTLE = "NO_BATTLE"
    APPROACHING = "APPROACHING"
    DRS_RANGE = "DRS_RANGE"
    ACTIVE_BATTLE = "ACTIVE_BATTLE"
    OVERTAKE = "OVERTAKE"
    DEFENDING = "DEFENDING"
    SEPARATING = "SEPARATING"


@dataclass
class Battle:
    ahead: int
    behind: int
    state: BattleState = BattleState.NO_BATTLE
    started_lap: int | None = None
    samples_in_state: int = 0
    min_gap_s: float | None = None
    last_gap_s: float | None = None


class BattleDetector:
    def __init__(self) -> None:
        self.battles: dict[tuple[int, int], Battle] = {}

    def _battle(self, ahead: int, behind: int) -> Battle:
        return self.battles.setdefault((ahead, behind), Battle(ahead=ahead, behind=behind))

    def update(self, ahead: int, behind: int, gap_s: float | None,
               lap: int | None = None,
               position_swap: bool = False,
               either_pitted_or_out: bool = False) -> Battle:
        """Feed one observation; returns the pair's new state."""
        b = self._battle(ahead, behind)

        if either_pitted_or_out or gap_s is None:
            if b.state is not BattleState.NO_BATTLE:
                b.state = BattleState.SEPARATING if gap_s is not None else BattleState.NO_BATTLE
                b.samples_in_state = 0
            return b

        b.last_gap_s = gap_s
        b.min_gap_s = gap_s if b.min_gap_s is None else min(b.min_gap_s, gap_s)

        prev = b.state

        if position_swap and prev in (BattleState.ACTIVE_BATTLE, BattleState.DRS_RANGE,
                                      BattleState.DEFENDING):
            # swap observed: report OVERTAKE once, then reset pair
            b.state = BattleState.OVERTAKE
            b.samples_in_state = 0
            b.started_lap = lap
            return b

        if gap_s > RESET_GAP:
            b.samples_in_state += 1
            if b.samples_in_state >= RESET_SAMPLES or prev is BattleState.NO_BATTLE:
                b.state = BattleState.NO_BATTLE
                b.samples_in_state = 0
            elif prev in (BattleState.APPROACHING, BattleState.DRS_RANGE):
                b.state = BattleState.SEPARATING
            return b

        close_samples_active = 0
        if gap_s <= ACTIVE_GAP:
            close_samples_active += 1
        b.samples_in_state = b.samples_in_state + 1 if (
            (prev is BattleState.ACTIVE_BATTLE and gap_s <= ACTIVE_GAP)
        ) else b.samples_in_state

        # deterministic transitions
        if prev in (BattleState.NO_BATTLE, BattleState.SEPARATING, BattleState.OVERTAKE):
            target = self._entry_state(gap_s)
            b.state = target
            b.samples_in_state = 1
            if target in (BattleState.DRS_RANGE, BattleState.ACTIVE_BATTLE) and \
                    b.started_lap is None:
                b.started_lap = lap
            return b

        if prev is BattleState.APPROACHING:
            b.state = self._entry_state(gap_s)
        elif prev is BattleState.DRS_RANGE:
            if gap_s <= ACTIVE_GAP:
                b.samples_in_state += 1
                if b.samples_in_state >= CONFIRM_SAMPLES:
                    b.state = BattleState.ACTIVE_BATTLE
                    b.started_lap = b.started_lap or lap
            elif gap_s > SEPARATE_GAP:
                b.state = BattleState.SEPARATING
                b.samples_in_state = 0
            elif gap_s > DRS_GAP:
                b.state = BattleState.DEFENDING
                b.samples_in_state = 0
        elif prev is BattleState.ACTIVE_BATTLE:
            if gap_s > ACTIVE_GAP:
                b.state = BattleState.DEFENDING if gap_s <= DRS_GAP else BattleState.SEPARATING
                b.samples_in_state = 0
        elif prev is BattleState.DEFENDING:
            if gap_s <= ACTIVE_GAP:
                b.state = BattleState.ACTIVE_BATTLE
                b.samples_in_state = 1
            elif gap_s > SEPARATE_GAP:
                b.state = BattleState.SEPARATING
                b.samples_in_state = 0

        return b

    @staticmethod
    def _entry_state(gap_s: float) -> BattleState:
        if gap_s <= ACTIVE_GAP:
            return BattleState.ACTIVE_BATTLE
        if gap_s <= DRS_GAP:
            return BattleState.DRS_RANGE
        if gap_s <= APPROACH_GAP:
            return BattleState.APPROACHING
        return BattleState.NO_BATTLE

    def active_battles(self) -> list[Battle]:
        return [b for b in self.battles.values()
                if b.state not in (BattleState.NO_BATTLE,)]
