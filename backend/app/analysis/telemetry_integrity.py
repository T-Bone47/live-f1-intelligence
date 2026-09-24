"""Telemetry integrity / coverage report over canonical TelemetryCarSample.

Pure measurement - it changes nothing, repairs nothing and fills nothing.
Used to state, with numbers, what a real telemetry capture actually
contains before it is used as validation evidence.

The gap threshold is the Phase 10.1B engine's own MAX_GAP_S (imported,
not redefined), so "a gap" means the same thing here as it does to the
distance integration that will consume these samples.
"""

from __future__ import annotations

from itertools import pairwise

from app.analysis.lap_distance import MAX_GAP_S
from app.core.models import TelemetryCarSample

OTHER_FIELDS = ("throttle_pct", "brake_pct", "rpm", "gear", "drs")


def telemetry_coverage(samples: list[TelemetryCarSample]) -> dict:
    """Coverage and integrity metrics, in the order the samples were given.

    Samples are NOT sorted first: an out-of-order capture must be reported
    as non-monotonic, not quietly fixed.
    """
    n = len(samples)
    if n == 0:
        return {"samples": 0, "first_ts": None, "last_ts": None, "duration_s": None,
                "largest_gap_s": None, "gaps_above_threshold": 0,
                "gap_threshold_s": MAX_GAP_S, "monotonic": True,
                "duplicate_timestamps": 0, "speed_valid_pct": None,
                "speed_min_kph": None, "speed_max_kph": None, "zero_speed_samples": 0,
                "field_available_pct": {f: None for f in OTHER_FIELDS}}

    deltas = [(b.ts - a.ts).total_seconds() for a, b in pairwise(samples)]
    speeds = [s.speed_kph for s in samples if s.speed_kph is not None]
    return {
        "samples": n,
        "first_ts": samples[0].ts,
        "last_ts": samples[-1].ts,
        "duration_s": (samples[-1].ts - samples[0].ts).total_seconds(),
        "largest_gap_s": max(deltas) if deltas else None,
        "gaps_above_threshold": sum(1 for d in deltas if d > MAX_GAP_S),
        "gap_threshold_s": MAX_GAP_S,
        "monotonic": all(d >= 0 for d in deltas),
        "duplicate_timestamps": sum(1 for d in deltas if d == 0),
        "speed_valid_pct": 100.0 * len(speeds) / n,
        "speed_min_kph": min(speeds) if speeds else None,
        "speed_max_kph": max(speeds) if speeds else None,
        "zero_speed_samples": sum(1 for v in speeds if v == 0),
        "field_available_pct": {
            f: 100.0 * sum(1 for s in samples if getattr(s, f) is not None) / n
            for f in OTHER_FIELDS
        },
    }
