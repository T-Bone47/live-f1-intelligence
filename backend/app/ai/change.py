"""ChangePack: structured diff between two context packs (Phase 6).

The LLM never compares thousands of raw events - we diff packs first:

    meaningful_changes: [{path, before, after}]
    summary_lines: human-readable deterministic lines

Only paths in WATCHED_PREFIXES are considered meaningful.
"""

from __future__ import annotations

from typing import Any

from app.realtime.differ import compute_diff

WATCHED_PREFIXES = (
    "leaderboard.", "fastest_lap", "weather.", "battles",
    "strategy_candidates", "recent_events",
)
MAX_CHANGES = 25


def build_change_pack(old_snapshot: dict[str, Any],
                      new_snapshot: dict[str, Any]) -> dict[str, Any]:
    changes, _removed = compute_diff(old_snapshot, new_snapshot)
    meaningful: list[dict] = []
    for path, after in sorted(changes.items()):
        if not path.startswith(WATCHED_PREFIXES):
            continue
        before = old_snapshot
        for part in path.split(".")[:-1]:
            before = before.get(part, {}) if isinstance(before, dict) else {}
        key = path.split(".")[-1]
        before_val = before.get(key) if isinstance(before, dict) else None
        if path.startswith("recent_events."):
            continue  # event churn is handled by the events feed itself
        meaningful.append({"path": path, "before": before_val, "after": after})
        if len(meaningful) >= MAX_CHANGES:
            break

    lines = [f"{m['path']}: {m['before']} -> {m['after']}" for m in meaningful[:12]]
    return {
        "pack": "change_v1",
        "meaningful_changes": meaningful,
        "summary_lines": lines,
        "count": len(meaningful),
    }
