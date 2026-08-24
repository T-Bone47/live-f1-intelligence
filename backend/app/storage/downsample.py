"""Deterministic downsampling for telemetry series (Phase 4).

LTTB (Largest-Triangle-Three-Buckets) - deterministic, order-preserving,
keeps visual shape at target point counts. RAW bypasses downsampling.

Frequency presets (target points per rendered trace):
    RAW  : as stored   (API caps range at 20 minutes)
    HIGH : ~600 points
    MEDIUM: ~300 points
    LOW  : ~120 points
"""

from __future__ import annotations

from typing import Sequence

FREQ_TARGETS = {"RAW": None, "HIGH": 600, "MEDIUM": 300, "LOW": 120}


def lttb(xs: Sequence[float], ys: Sequence[float],
         target_points: int) -> tuple[list[float], list[float]]:
    """Downsample (xs, ys) to ~target_points using LTTB.

    Deterministic; returns input unchanged when already within budget.
    """
    n = len(xs)
    if target_points is None or n <= max(target_points, 3):
        return list(xs), list(ys)

    every = (n - 2) / (target_points - 2)
    out_x: list[float] = [xs[0]]
    out_y: list[float] = [ys[0]]
    a_index = 0

    for i in range(1, target_points - 1):
        bucket_start = int((i - 1) * every) + 1
        bucket_end = min(int(i * every) + 1, n)
        next_start = min(int(i * every) + 1, n)
        next_end = min(int((i + 1) * every) + 1, n)

        avg_x = sum(xs[next_start:next_end]) / max(next_end - next_start, 1)
        avg_y = sum(ys[next_start:next_end]) / max(next_end - next_start, 1)

        best_index = bucket_start
        best_area = -1.0
        for j in range(bucket_start, bucket_end):
            ax, ay = xs[a_index], ys[a_index]
            area = abs(
                (ax - avg_x) * (ys[j] - ay) - (ax - xs[j]) * (avg_y - ay)
            ) * 0.5
            if area > best_area:
                best_area = area
                best_index = j
        out_x.append(xs[best_index])
        out_y.append(ys[best_index])
        a_index = best_index

    out_x.append(xs[-1])
    out_y.append(ys[-1])
    return out_x, out_y


def normalize_frequency(raw: str | None) -> str:
    f = (raw or "MEDIUM").upper()
    return f if f in FREQ_TARGETS else "MEDIUM"
