# CHAMPIONSHIP_INTELLIGENCE.md

Deterministic HYPOTHETICAL projections only.

Input: current finishing order (leaderboard positions) + season standings
(Jolpica StandingsEntry store). Points assumption: 2026 table
25-18-15-12-10-8-6-4-2-1 with no fastest-lap point (documented).

Output per driver: hypothetical_points_this_race, current_season_points,
projected_total, label HYPOTHETICAL - assumes current order holds.
Constructors: summed gains grouped by constructor_ref.

Nothing predicts finishing order; scenarios answer exactly IF-CURRENT-ORDER-
HOLDS questions and feed CHAMPIONSHIP_IMPLICATION events in future phases.
