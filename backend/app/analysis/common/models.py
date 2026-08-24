"""Common types for the deterministic analysis layer (Phase 2).

Every output of this layer carries DERIVED provenance with a calculation
version, so any metric can be traced to the exact code that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

CALC_VERSION = "analysis-2.0.0"


class Severity(str, Enum):
    INFO = "INFO"
    NOTABLE = "NOTABLE"
    IMPORTANT = "IMPORTANT"
    CRITICAL = "CRITICAL"


class LapFlag(str, Enum):
    """Deterministic lap classification reasons (mutually attachable)."""

    PIT_OUT = "PIT_OUT"
    PIT_IN = "PIT_IN"
    DELETED = "DELETED"
    YELLOW = "YELLOW"
    DOUBLE_YELLOW = "DOUBLE_YELLOW"
    SAFETY_CAR = "SAFETY_CAR"
    VSC = "VSC"
    RED_FLAG = "RED_FLAG"
    OUTLIER = "OUTLIER"
    INACCURATE = "INACCURATE"
    FORMATION = "FORMATION"


class LapClass(str, Enum):
    FLYING = "FLYING"
    PIT_OUT = "PIT_OUT"
    PIT_IN = "PIT_IN"
    IN_LAP = "IN_LAP"  # alias kept distinct from PIT_IN semantics below
    INVALID = "INVALID"
    OUTLIER = "OUTLIER"
    REPRESENTATIVE = "REPRESENTATIVE"
    UNCLASSIFIED = "UNCLASSIFIED"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"  # insufficient data - value absent rather than guessed


class CleanAir(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


@dataclass
class DerivedProvenance:
    """Provenance stamped onto every derived metric/event."""

    session_id: str
    calculated_at: datetime
    calc_version: str = CALC_VERSION
    source_provider: str | None = None      # upstream feed feeding the calc
    input_event_ids: tuple[str, ...] = ()   # envelope ids where practical
    confidence: Confidence = Confidence.NONE

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "DERIVED",
            "session_id": self.session_id,
            "calculated_at": self.calculated_at.isoformat(),
            "calc_version": self.calc_version,
            "source_provider": self.source_provider,
            "input_event_ids": list(self.input_event_ids),
            "confidence": self.confidence.value,
        }


@dataclass
class IntelligenceEvent:
    """A deterministic, deduplicated analytical event."""

    event_key: str                 # deterministic identity -> dedupe contract
    event_type: str                # e.g. "PURPLE_SECTOR", "BATTLE_STARTED"
    session_id: str
    timestamp: datetime
    driver_numbers: tuple[int, ...] = ()
    severity: Severity = Severity.INFO
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()  # human-readable provenance trail
    provenance: DerivedProvenance | None = None
    prediction: bool = False       # True ONLY for forward-looking estimates

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "drivers": list(self.driver_numbers),
            "severity": self.severity.value,
            "metrics": self.metrics,
            "evidence": list(self.evidence),
            "provenance": self.provenance.as_dict() if self.provenance else None,
            "prediction": self.prediction,
        }


@dataclass
class MetricResult:
    """A single derived metric value with full traceability."""

    name: str
    value: Any                     # None == genuinely not computable
    unit: str | None = None
    provenance: DerivedProvenance | None = None
    notes: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        return self.value is not None


# ---- shared deterministic helpers ------------------------------------------


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def mad_outliers(values: list[float], threshold: float = 2.5) -> list[int]:
    """Indices of MAD-based outliers. Deterministic; empty-safe."""
    if len(values) < 4:
        return []
    med = median(values) or 0.0
    deviations = [abs(v - med) for v in values]
    mad = median(deviations) or 0.0
    if mad == 0.0:  # all-equal or degenerate: fall back to none removed
        return []
    return [
        i for i, d in enumerate(deviations)
        if 0.6754 * d / mad > threshold
    ]


def linfit_slope_intercept(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """OLS y = a + b x. Returns (a, b, r_squared). Empty-safe callers guard."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx if sxx else 0.0
    a = my - b * mx
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return a, b, max(0.0, r2)
