"""Data-quality monitor + latency measurement.

Developer-facing instrumentation only (not final UI). Tracks per-channel and
per-driver availability, malformed/duplicate counters, reconnect counts, and
source->ingestion latency statistics (min/avg/p50/p95/max).

Latency is ONLY meaningful for class-A live data; historical backfills report
it but are labeled so nobody mistakes backfill speed for live latency.
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from datetime import datetime
from typing import Deque

from app.core.enums import ProvenanceClass


class DataQualityMonitor:
    def __init__(self, latency_sample_cap: int = 20000) -> None:
        self.session: dict = {}
        self.drivers_seen: set[int] = set()
        self.channel_last_ts: dict[str, datetime] = {}
        self.channel_counts: dict[str, int] = defaultdict(int)
        self.driver_channel_seen: dict[str, set[int]] = defaultdict(set)
        self.malformed_events = 0
        self.duplicate_events = 0
        self.reconnect_count = 0
        self.shed_events = 0
        # per-provider dimensions (Phase 1.5)
        self.provider_channel_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.provider_latency: dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=latency_sample_cap)
        )
        self.provider_malformed: dict[str, int] = defaultdict(int)
        self.provider_duplicates: dict[str, int] = defaultdict(int)
        self._latency: Deque[float] = deque(maxlen=latency_sample_cap)
        self._latency_live_only: Deque[float] = deque(maxlen=latency_sample_cap)
        # Phase 7: per-channel latency breakdown (timing/telemetry/position/
        # sector/tyre/weather/rc) for live acceptance measurement
        self._channel_latency: dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=latency_sample_cap))
        self.started_at = datetime.now()

    # ------------------------------------------------------------- hooks ----

    def note_event(
        self,
        event_type: str,
        driver_number: int | None,
        source_timestamp: datetime | None,
        ingestion_timestamp: datetime,
        provenance_class: ProvenanceClass,
        source: str = "unknown",
    ) -> None:
        channel = event_type.split(".")[0]
        self.channel_counts[channel] += 1
        self.provider_channel_counts[source][channel] += 1
        self.channel_last_ts[event_type] = ingestion_timestamp
        if driver_number is not None:
            self.drivers_seen.add(driver_number)
            self.driver_channel_seen[channel].add(driver_number)
        if source_timestamp is not None:
            delta = (ingestion_timestamp - source_timestamp).total_seconds()
            if 0 <= delta < 86_400 * 7:  # ignore absurd clock skew
                self._latency.append(delta)
                self._channel_latency[channel].append(delta)
                if provenance_class == ProvenanceClass.A:
                    self._latency_live_only.append(delta)
                self.provider_latency[source].append(delta)

    def note_malformed(self, source: str = "unknown") -> None:
        self.malformed_events += 1
        self.provider_malformed[source] += 1

    def note_duplicate(self, source: str = "unknown") -> None:
        self.duplicate_events += 1
        self.provider_duplicates[source] += 1

    def note_reconnect(self) -> None:
        self.reconnect_count += 1

    # ------------------------------------------------------------ report ----

    @staticmethod
    def _latency_stats(samples: Deque[float]) -> dict:
        if not samples:
            return {
                "samples": 0,
                "min_s": None,
                "avg_s": None,
                "p50_s": None,
                "p95_s": None,
                "max_s": None,
            }
        ordered = sorted(samples)
        n = len(ordered)

        def pct(p: float) -> float:
            idx = min(n - 1, max(0, round((p / 100.0) * (n - 1))))
            return ordered[idx]

        return {
            "samples": n,
            "min_s": round(ordered[0], 3),
            "avg_s": round(statistics.fmean(ordered), 3),
            "p50_s": round(pct(50), 3),
            "p95_s": round(pct(95), 3),
            "max_s": round(ordered[-1], 3),
        }

    def report(self) -> dict:
        return {
            "session": dict(self.session),
            "drivers_detected": len(self.drivers_seen),
            "driver_numbers": sorted(self.drivers_seen),
            "channel_counts": dict(sorted(self.channel_counts.items())),
            "telemetry_availability_per_driver": {
                "car_data": len(self.driver_channel_seen.get("telemetry", set())),
            },
            "availability_by_driver": {
                ch: sorted(nums) for ch, nums in sorted(self.driver_channel_seen.items())
            },
            "malformed_events": self.malformed_events,
            "duplicate_events": self.duplicate_events,
            "reconnects": self.reconnect_count,
            "shed_events": self.shed_events,
            "latency_all": self._latency_stats(self._latency),
            "latency_live_class_a": self._latency_stats(self._latency_live_only),
            "channel_latency": {
                ch: self._latency_stats(dq)
                for ch, dq in sorted(self._channel_latency.items())
            },
            "providers": {
                name: {
                    "channel_counts": dict(sorted(chans.items())),
                    "malformed": self.provider_malformed.get(name, 0),
                    "duplicates": self.provider_duplicates.get(name, 0),
                    "latency": self._latency_stats(self.provider_latency.get(name, [])),
                }
                for name, chans in sorted(self.provider_channel_counts.items())
            },
            "last_event_at": (
                max(self.channel_last_ts.values()).isoformat()
                if self.channel_last_ts else None
            ),
            "monitor_started_at": self.started_at.isoformat(),
        }

    def render_text(self) -> str:
        r = self.report()
        lines: list[str] = []
        sess = r["session"]
        lines.append("=" * 60)
        lines.append("DATA QUALITY")
        lines.append("=" * 60)
        name = sess.get("session_name") or sess.get("provider_session_key") or "?"
        lines.append(f"Session: {name} ({sess.get('country_code', '?')})")
        lines.append(f"Status : {sess.get('status', '?')}")
        start = sess.get("date_start", "-")
        lines.append(f"Start  : {start}")
        lines.append(f"Drivers: {r['drivers_detected']}")
        for ch in ("lap", "sector", "tyre", "pit", "weather", "rcm", "position", "timing"):
            count = r["channel_counts"].get(ch)
            label = {"rcm": "RaceControl", "timing": "Intervals", "tyre": "Tyres"}.get(ch, ch.capitalize())
            lines.append(f"{label:<11}: {'n/a' if count is None else count} events")
        car_drivers = r["availability_by_driver"].get("telemetry", [])
        lines.append(f"Telemetry (car): {len(car_drivers)} drivers with samples")
        lat = r["latency_live_class_a"]
        if lat["samples"]:
            lines.append(
                f"Live latency (class A): avg {lat['avg_s']}s p50 {lat['p50_s']}s "
                f"p95 {lat['p95_s']}s (min {lat['min_s']}s / max {lat['max_s']}s)"
            )
        else:
            all_lat = r["latency_all"]
            if all_lat["samples"] and all_lat["avg_s"] and all_lat["avg_s"] > 3600:
                lines.append(
                    f"Latency: HISTORICAL BACKFILL (not live) - avg source age "
                    f"{all_lat['avg_s'] / 3600:.1f}h"
                )
            else:
                lines.append("Latency: no measurable live samples")
        lines.append(f"Malformed: {r['malformed_events']}  Duplicates: {r['duplicate_events']}  "
                     f"Reconnects: {r['reconnects']}")
        lines.append("=" * 60)
        return "\n".join(lines)
