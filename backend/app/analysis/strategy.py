"""Deterministic strategy primitives (Phase 2).

These are MEASURABLE INPUTS for a future optimizer - never recommendations
and never an "optimal strategy". Every threshold is a documented constant.

- pit_loss_estimate_s: median observed lane_duration of completed stops this
  session. None until at least MIN_STOPS (2) stops observed - no invented
  circuit defaults.
- compound_baseline_life: DOCUMENTED ASSUMPTIONS (configurable): SOFT 15,
  MEDIUM 25, HARD 35 laps; INTERMEDIATE/WET excluded from dry-window logic.
- pit_window_candidate(driver): opens when tyre_age >= baseline_life - 3
  (wear-out approach) while session has >= 8 laps remaining context absent
  (v1: age-based only, race-length awareness deferred to optimizer).
- undercut_indicator: gap_to_ahead <= UNDERCUT_GAP (2.5 s) AND defender stint
  age - attacker stint age <= -4 (attacker on clearly older tyres is the one
  threatening... inverted: attacker FRESHER tyres make undercut lethal) ->
  v1 deterministic rule: attacker_tyre_age + 4 <= defender_tyre_age and
  gap <= 2.5.
- overcut_indicator: defender stays out with gap <= OVERCUT_GAP (1.8 s) while
  attacker just pitted (attacker in pit) - flag only.
- expected_rejoin_position: count of cars whose current numeric gap-to-leader
  < mine + pit_loss (they remain ahead). Symbolic-gap cars counted ahead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

UNDERCUT_GAP = 2.5
OVERCUT_GAP = 1.8
BASELINE_LIFE = {
    "SOFT": 15,
    "MEDIUM": 25,
    "HARD": 35,
}
MIN_STOPS_FOR_PIT_LOSS = 2


@dataclass
class StrategyPrimitives:
    session_id: str
    pit_lane_durations: list[float] = field(default_factory=list)

    # ---------------------------------------------------------- pit loss ----

    def fold_pit_stop(self, lane_duration_s: float | None) -> None:
        if lane_duration_s and lane_duration_s < 300:  # ignore red-flag parkings
            self.pit_lane_durations.append(lane_duration_s)

    def pit_loss_estimate(self) -> tuple[float | None, int]:
        if len(self.pit_lane_durations) < MIN_STOPS_FOR_PIT_LOSS:
            return None, len(self.pit_lane_durations)
        s = sorted(self.pit_lane_durations)
        n = len(s)
        med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
        return round(med, 2), n

    # --------------------------------------------------------- pit window ---

    def pit_window_candidate(self, *, compound: str | None, tyre_age: int | None,
                             ) -> tuple[int, int] | None:
        if compound is None or tyre_age is None:
            return None
        base = BASELINE_LIFE.get(compound.upper())
        if base is None:
            return None  # inters/wets/unknown: no dry-window claim
        if tyre_age >= base - 3:
            return (tyre_age, min(base + 2, tyre_age + 6))
        return None

    # --------------------------------------------------- under/over cut -----

    def undercut_indicator(self, *, gap_to_ahead_s: float | None,
                           attacker_age: int | None,
                           defender_age: int | None) -> bool:
        if gap_to_ahead_s is None or attacker_age is None or defender_age is None:
            return False
        return gap_to_ahead_s <= UNDERCUT_GAP and (attacker_age + 4) <= defender_age

    def overcut_indicator(self, *, gap_to_ahead_s: float | None,
                          ahead_in_pit: bool) -> bool:
        return bool(gap_to_ahead_s is not None and gap_to_ahead_s <= OVERCUT_GAP
                    and ahead_in_pit)

    # ------------------------------------------------------------- rejoin ----

    def expected_rejoin_position(self, *, my_gap_to_leader: float | None,
                                 all_gaps: dict[int, float | None],
                                 symbolic_ahead_count: int = 0) -> int | None:
        if my_gap_to_leader is None:
            return None
        loss, _n = self.pit_loss_estimate()
        effective = my_gap_to_leader + (loss or 0.0)
        ahead = sum(1 for g in all_gaps.values() if g is not None and g < effective)
        return ahead + symbolic_ahead_count + 1
