# BATTLE_INTELLIGENCE_2.md

Same deterministic FSM thresholds as Phase 2; this layer ADDS structured
context computed at enrichment time:

tyre_delta_laps (attacker age - defender age), pace_advantage_s (defender
rolling5 - attacker rolling5), closing_rate (GapEngine pair), traffic state of
attacker, drs status (UNKNOWN under OpenF1).

New event names mapped from FSM transitions:
APPROACHING entry -> BATTLE_FORMING; DRS_RANGE/ACTIVE entry ->
BATTLE_ESCALATING; ACTIVE sustained -> BATTLE_STABLE (bucketed dedupe);
SEPARATING -> BATTLE_BREAKING; swap -> OVERTAKE; DEFENDING entry -> DEFENDING.
No overtake probability model (explicitly deferred to ML phase).
