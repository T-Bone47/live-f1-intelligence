"""Realtime observability metrics (Phase 3)."""

from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


def _percentiles(samples: Deque[float]) -> dict[str, float | None]:
    if not samples:
        return {"p50": None, "p95": None}
    ordered = sorted(samples)
    n = len(ordered)
    return {
        "p50": round(ordered[n // 2], 4),
        "p95": round(ordered[min(n - 1, int(n * 0.95))], 4),
    }


@dataclass
class RealtimeMetrics:
    started_at: float = field(default_factory=time.monotonic)
    provider_name: str = "unknown"
    provider_status: str = "IDLE"           # IDLE|CONNECTING|CONNECTED|STALE|FAILED
    session_id: str | None = None
    events_seen: int = 0
    analysis_latency_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    snapshot_latency_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    diff_latency_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    ws_broadcast_latency_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    delta_bytes: Deque[int] = field(default_factory=lambda: deque(maxlen=500))
    clients_connected: int = 0
    reconnects: int = 0
    slow_client_evictions: int = 0
    telemetry_dropped_stale: int = 0
    deltas_dropped_for_slow_clients: int = 0
    redis_enabled: bool = False
    redis_status: str = "DISABLED"
    last_error: str | None = None

    def observe_analysis(self, ms: float) -> None:
        self.analysis_latency_ms.append(ms)

    def observe_snapshot(self, ms: float) -> None:
        self.snapshot_latency_ms.append(ms)

    def observe_diff(self, ms: float, size_bytes: int) -> None:
        self.diff_latency_ms.append(ms)
        self.delta_bytes.append(size_bytes)

    def observe_ws(self, ms: float) -> None:
        self.ws_broadcast_latency_ms.append(ms)

    def events_per_sec(self) -> float:
        elapsed = max(time.monotonic() - self.started_at, 1e-6)
        return round(self.events_seen / elapsed, 1)

    def as_dict(self) -> dict:
        return {
            "provider": {
                "name": self.provider_name,
                "status": self.provider_status,
                "latency": None,  # populated from quality monitor when attached
            },
            "session_id": self.session_id,
            "events_per_sec": self.events_per_sec(),
            "events_total": self.events_seen,
            "analysis_latency_ms": _percentiles(self.analysis_latency_ms),
            "snapshot_latency_ms": _percentiles(self.snapshot_latency_ms),
            "diff_latency_ms": _percentiles(self.diff_latency_ms),
            "diff_size_bytes_p50": (
                round(statistics.median(self.delta_bytes))
                if self.delta_bytes else None),
            "ws_broadcast_latency_ms": _percentiles(self.ws_broadcast_latency_ms),
            "websocket": {"clients": self.clients_connected},
            "reconnects": self.reconnects,
            "slow_client_evictions": self.slow_client_evictions,
            "telemetry_dropped_stale": self.telemetry_dropped_stale,
            "deltas_dropped_slow_clients": self.deltas_dropped_for_slow_clients,
            "redis": {"enabled": self.redis_enabled, "status": self.redis_status},
            "last_error": self.last_error,
            "uptime_s": round(time.monotonic() - self.started_at, 1),
        }
