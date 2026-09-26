"""Phase 12A: the claim-scoped validation gate.

A session's geometry is only as good as the measured error of placing a
timed event on it (timing_lines). Claims are gated by what they need:

- MAP_SECTOR (track map, sector membership, segment regions): every official
  line's p95 dispersion <= 20 m, and the inter-line distances agree within
  20 m across reference laps.
- CORNER (corner-level metre claims): every line's p95 <= 5 m.

The 20 m and 5 m thresholds are product policy chosen by the user
(2026-09-26), not tuned to the data. MIN_CROSSINGS = 60 leaves at least three
observations above a p95 - PROVISIONAL. Without a cited lap length nothing
can pass: the thresholds are in metres.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.spatial.circuits import CitedLength
from app.spatial.timing_lines import LINES, LineMeasurement

MAP_SECTOR_P95_M = 20.0
CORNER_P95_M = 5.0
MIN_CROSSINGS = 60
INDEPENDENCE_MAX_M = 20.0


@dataclass(frozen=True)
class GateResult:
    claim: str
    passed: bool
    threshold_m: float
    observed_p95_m: dict[str, float | None]
    reasons: tuple[str, ...]


def _claim(claim: str, threshold: float, lines: Mapping[str, LineMeasurement] | None,
           cited: CitedLength | None, extra: tuple[str, ...]) -> GateResult:
    reasons: list[str] = []
    observed: dict[str, float | None] = dict.fromkeys(LINES)
    if cited is None:
        reasons.append("NO_CITED_LAP_LENGTH")
    if lines is None:
        reasons.append("NO_REFERENCE")
    else:
        for name in LINES:
            m = lines.get(name)
            p95 = None if m is None or m.dispersion_m is None else m.dispersion_m["p95"]
            observed[name] = p95
            if m is None or m.n < MIN_CROSSINGS:
                reasons.append(f"TOO_FEW_CROSSINGS:{name}")
            elif p95 is not None and p95 > threshold:
                reasons.append(f"P95_ABOVE_THRESHOLD:{name}")
    reasons += extra
    return GateResult(claim=claim, passed=not reasons, threshold_m=threshold,
                      observed_p95_m=observed, reasons=tuple(reasons))


def evaluate_gate(lines: Mapping[str, LineMeasurement] | None, independence_m: float | None,
                  cited: CitedLength | None) -> dict[str, GateResult]:
    independence: tuple[str, ...] = ()
    if lines is not None:
        if independence_m is None:
            independence = ("INDEPENDENCE_UNMEASURED",)
        elif independence_m > INDEPENDENCE_MAX_M:
            independence = ("REFERENCE_DEPENDENT",)
    return {"MAP_SECTOR": _claim("MAP_SECTOR", MAP_SECTOR_P95_M, lines, cited, independence),
            "CORNER": _claim("CORNER", CORNER_P95_M, lines, cited, ())}
