"""DRS intelligence (Phase 5) - provider-dependent by design.

OpenF1 intervals carry no DRS state; the direct SignalR TimingData feed does
(verified topic presence; per-car DRS flags arrive in feed frames). Until such
frames are captured, every query returns UNKNOWN and capabilities are reported
honestly. No DRS effect is ever claimed from insufficient data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.analysis.common.models import Confidence


class DRSAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class DRSIntel:
    provider_supports_drs: bool
    availability: DRSAvailability = DRSAvailability.UNKNOWN
    usage_laps: int = 0
    proximity_gap_s: float | None = None
    train_detected: bool | None = None      # >=3 cars within 1s chain
    confidence: Confidence = Confidence.NONE
    note: str = ""


class DRSAnalyzer:
    """Feed with (driver, drs_enabled, gap) samples when the provider offers
    them; without samples everything stays UNKNOWN."""

    def __init__(self, provider_supports_drs: bool) -> None:
        self.supported = provider_supports_drs
        self._enabled_samples: dict[int, list[bool]] = {}
        self._trains: list[list[float]] = []

    def fold(self, driver_number: int, drs_enabled: bool | None,
             gap_to_ahead_s: float | None) -> None:
        if not self.supported or drs_enabled is None:
            return
        self._enabled_samples.setdefault(driver_number, []).append(drs_enabled)
        if gap_to_ahead_s is not None:
            for chain in self._trains:
                pass  # train assembly handled at snapshot time from positions

    def intel_for(self, driver_number: int) -> DRSIntel:
        if not self.supported:
            return DRSIntel(
                provider_supports_drs=False,
                note="current provider exposes no per-car DRS state",
            )
        samples = self._enabled_samples.get(driver_number)
        if not samples:
            return DRSIntel(provider_supports_drs=True,
                            confidence=Confidence.NONE)
        usage = sum(1 for s in samples if s)
        return DRSIntel(
            provider_supports_drs=True,
            availability=DRSAvailability.AVAILABLE if usage else
            DRSAvailability.NOT_AVAILABLE,
            usage_laps=usage,
            confidence=Confidence.MEDIUM if len(samples) >= 5 else Confidence.LOW,
        )
