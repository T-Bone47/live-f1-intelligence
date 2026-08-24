"""Championship intelligence (Phase 5): deterministic HYPOTHETICAL projections.

Points table: 2026 scoring assumption 25-18-15-12-10-8-6-4-2-1 (no fastest-lap
point) - documented ASSUMPTION. Standings come from canonical StandingsEntry
rows (Jolpica). Projections answer exactly one question:

    IF the current on-track order held to the end, who gains/loses what?

Nothing here predicts finishing order.
"""

from __future__ import annotations

POINTS_2026 = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]


def points_for_position(position: int | None) -> int:
    if position is None or position < 1 or position > len(POINTS_2026):
        return 0
    return POINTS_2026[position - 1]


def project_from_order(*, current_order: list[dict],
                       standings: dict[str, dict]) -> dict:
    """current_order: [{driver_ref|family_name, position}] from leaderboard.
    standings: {driver_ref: {"points": float, "constructor_ref": str|None,
                             "position": int|None}}"""

    deltas: list[dict] = []
    constructor_delta: dict[str, float] = {}
    for row in current_order:
        ref = row.get("driver_ref") or ""
        pos = row.get("position")
        gained = points_for_position(pos)
        cur = standings.get(ref)
        entry = {
            "driver": row.get("family_name") or ref or f"P{pos}",
            "hypothetical_points_this_race": gained,
            "current_season_points": cur["points"] if cur else None,
            "projected_total": round((cur["points"] if cur else 0) + gained, 1)
            if cur else None,
            "label": "HYPOTHETICAL - assumes current order holds",
        }
        deltas.append(entry)
        cref = (cur or {}).get("constructor_ref")
        if cref:
            constructor_delta[cref] = constructor_delta.get(cref, 0) + gained

    return {
        "available": bool(standings),
        "assumption": "2026 points 25-18-15-12-10-8-6-4-2-1, no FL point",
        "drivers": deltas,
        "constructors_if_order_holds": {k: round(v, 1)
                                        for k, v in sorted(constructor_delta.items(),
                                                           key=lambda kv: -kv[1])},
    }
