"""Battle intelligence 2.0 (Phase 5): contextual enrichment of the FSM.

Wraps the Phase-2 BattleDetector states with structured context computed from
other analyzers at snapshot time - no new thresholds, no ML.

Context per active battle:
    tyre_advantage   attacker (behind) compound/age vs defender
    pace_advantage_s defender rolling5 - attacker rolling5 (negative=attacker faster)
    closing_rate     from GapEngine pair samples
    traffic          TrafficState of the attacking car
    drs              DRS intel (usually UNKNOWN under OpenF1)

Events emitted through the standard engine:
    BATTLE_FORMING   entry to APPROACHING
    BATTLE_ESCALATING entry to DRS_RANGE / ACTIVE_BATTLE
    BATTLE_STABLE    ACTIVE sustained >=4 samples without state change
    BATTLE_BREAKING  SEPARATING
    OVERTAKE         position swap (existing)
    DEFENDING        entry to DEFENDING
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.battles import Battle, BattleState


@dataclass
class BattleContext:
    battle: Battle
    tyre_delta_laps: int | None = None       # attacker_age - defender_age
    pace_advantage_s: float | None = None    # negative = attacker quicker
    closing_rate: float | None = None
    traffic_state: str = "UNKNOWN"
    drs: str = "UNKNOWN"

    def as_metrics(self) -> dict:
        return {
            "state": self.battle.state.value,
            "min_gap_s": self.battle.min_gap_s,
            "last_gap_s": self.battle.last_gap_s,
            "tyre_delta_laps": self.tyre_delta_laps,
            "pace_advantage_s": self.pace_advantage_s,
            "closing_rate_per_sample": self.closing_rate,
            "traffic": self.traffic_state,
            "drs": self.drs,
        }


def enrich(battle: Battle, *, attacker_tyre_age: int | None,
           defender_tyre_age: int | None,
           attacker_rolling5: float | None, defender_rolling5: float | None,
           closing_rate: float | None, traffic_state: str,
           drs_state: str) -> BattleContext:
    tyre_delta = None
    if attacker_tyre_age is not None and defender_tyre_age is not None:
        tyre_delta = attacker_tyre_age - defender_tyre_age
    pace_adv = None
    if attacker_rolling5 is not None and defender_rolling5 is not None:
        pace_adv = round(defender_rolling5 - attacker_rolling5, 3)
    return BattleContext(
        battle=battle,
        tyre_delta_laps=tyre_delta,
        pace_advantage_s=pace_adv,
        closing_rate=closing_rate,
        traffic_state=traffic_state,
        drs=drs_state,
    )


def event_type_for_transition(prev: BattleState, curr: BattleState) -> str | None:
    if prev is BattleState.NO_BATTLE and curr is BattleState.APPROACHING:
        return "BATTLE_FORMING"
    if curr in (BattleState.DRS_RANGE, BattleState.ACTIVE_BATTLE) and \
            prev in (BattleState.APPROACHING, BattleState.DEFENDING):
        return "BATTLE_ESCALATING"
    if prev is BattleState.ACTIVE_BATTLE and curr is BattleState.ACTIVE_BATTLE:
        return "BATTLE_STABLE"      # dedupe key includes sample bucket upstream
    if curr is BattleState.SEPARATING:
        return "BATTLE_BREAKING"
    if curr is BattleState.DEFENDING:
        return "DEFENDING"
    return None
