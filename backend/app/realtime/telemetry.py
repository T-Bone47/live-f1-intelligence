"""Telemetry coalescing (Phase 3).

Raw car telemetry arrives at ~3.5 Hz per car. Broadcasting every sample to
every subscribed client is wasteful; policy:

- latest-wins coalescing per driver: intermediate samples are replaced
  (stale intermediates dropped, counted);
- flush cadence configurable (default 5 Hz) independent of arrival rate;
- only subscribed drivers are tracked;
- fields exposed verbatim; missing channels stay absent (never zeroed).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TelemetryCoalescer:
    flush_interval_s: float = 0.2          # 5 Hz default
    _latest: dict[int, dict] = field(default_factory=dict)
    _dropped_stale: int = 0

    def offer(self, driver_number: int, sample: dict) -> bool:
        """Store latest sample for driver. Returns True if it replaced an
        unflushed previous one (i.e., a stale-intermediate drop)."""
        existed = driver_number in self._latest
        self._latest[driver_number] = sample
        if existed:
            self._dropped_stale += 1
            return True
        return False

    def due(self, now_monotonic: float, last_flush: float) -> bool:
        return (now_monotonic - last_flush) >= self.flush_interval_s

    def drain(self) -> dict[int, list[dict]]:
        out = {dn: [sample] for dn, sample in self._latest.items()}
        self._latest.clear()
        return out

    @property
    def dropped_stale(self) -> int:
        return self._dropped_stale

    def __len__(self) -> int:
        return len(self._latest)
