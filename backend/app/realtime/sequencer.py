"""Per-session monotonic sequence + bounded history for resume (Phase 3).

All outbound frames share one sequence space. The ring keeps the last N
frames so reconnecting clients can resume by last_received_seq; older gaps
degrade to a fresh full snapshot (never event replay of millions of items).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SequencedFrame:
    seq: int
    kind: str
    payload: dict[str, Any]


class SequenceHistory:
    def __init__(self, capacity: int = 2000) -> None:
        self._seq = 0
        self._ring: deque[SequencedFrame] = deque(maxlen=capacity)

    @property
    def current(self) -> int:
        return self._seq

    def next(self, kind: str, payload: dict[str, Any]) -> SequencedFrame:
        self._seq += 1
        frame = SequencedFrame(seq=self._seq, kind=kind, payload=payload)
        self._ring.append(frame)
        return frame

    def since(self, last_received: int) -> list[SequencedFrame]:
        """Frames with seq > last_received still held in history."""
        return [f for f in self._ring if f.seq > last_received]

    @property
    def oldest_available(self) -> int | None:
        return self._ring[0].seq if self._ring else None
