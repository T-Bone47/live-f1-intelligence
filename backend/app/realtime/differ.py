"""Snapshot diff engine (Phase 3).

Flat-path diff over the snapshot dict:

    changes: {"leaderboard.1.position": 2, "weather.air_temp_c": 19.2, ...}
    removed: ["battles.3", "recent_events.0", ...]

Rules:
- Lists are treated as ATOMIC values (replaced wholesale) except where a
  stable key exists - we keep v1 simple: lists atomic; documented.
- Dicts recurse with dotted paths.
- Values compared by equality; NaN-safe via != on floats (NaN!=NaN would
  spam; we normalize NaN->None at snapshot build time upstream).
- Diff cost O(nodes); typical race delta < 200 paths (<4 KB JSON).
"""

from __future__ import annotations

from typing import Any


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, path))
        else:
            out[path] = v
    return out


def compute_diff(old: dict[str, Any], new: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return (changes, removed) between two snapshot dicts."""
    old_flat = _flatten(old)
    new_flat = _flatten(new)
    changes: dict[str, Any] = {}
    for path, value in new_flat.items():
        if path not in old_flat or old_flat[path] != value:
            changes[path] = value
    removed = [path for path in old_flat if path not in new_flat]
    return changes, removed


class SnapshotDiffer:
    """Stateful differ holding the last published snapshot."""

    def __init__(self) -> None:
        self._last: dict[str, Any] | None = None

    def first_diff(self, snap: dict[str, Any]) -> tuple[bool, dict[str, Any], list[str]]:
        """Returns (is_full, changes, removed). Full when no prior state."""
        if self._last is None:
            self._last = snap
            return True, snap, []
        changes, removed = compute_diff(self._last, snap)
        self._last = snap
        return False, changes, removed

    @property
    def has_state(self) -> bool:
        return self._last is not None

    def reset(self) -> None:
        self._last = None
