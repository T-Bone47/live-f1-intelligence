"""Event identity + deduplication (Phase 2 contract).

Deterministic event key format:

    {session_id}|{event_type}|{identity}

where `identity` is event-type-specific (documented in EVENT_DEFINITIONS.md).
The same real-world occurrence ALWAYS maps to the same key regardless of how
many polling cycles re-derive it; the deduper suppresses repeats while the
key stays in cache. Re-emission after eviction is possible for very long
sessions - keys include lap/phase buckets so semantic repeats still differ.
"""

from __future__ import annotations

from collections import OrderedDict


class EventDeduplicator:
    def __init__(self, capacity: int = 50_000) -> None:
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._capacity = capacity

    @staticmethod
    def build_key(session_id: str, event_type: str, identity: str) -> str:
        return f"{session_id}|{event_type}|{identity}"

    def is_duplicate(self, key: str) -> bool:
        if key in self._seen:
            self._seen.move_to_end(key)
            return True
        self._seen[key] = None
        if len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
        return False

    def __len__(self) -> int:
        return len(self._seen)
