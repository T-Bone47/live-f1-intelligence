"""Sector engine (Phase 2): PB/SB/purple-green-yellow + theoretical lap.

Definitions (documented in METRIC_DEFINITIONS.md and implemented exactly):

- Personal best (PB) sector: driver's fastest VALID time for sector i.
- Session best / PURPLE: fastest valid time for sector i across all drivers.
- On a new valid sector time t for driver d, sector i:
    improved = t < d.PB[i] (or first sample)
    purple   = improved AND t < session_best[i]
    class    = PURPLE | GREEN(improvement, not purple) | YELLOW(slower)
- Sector delta = t - d.PB[i]  (negative == improvement vs prior PB)
- theoretical_lap(d) = sum(d.PB[1..3]); None if ANY of the three is missing.
- Deleted laps are excluded from PB/SB via the correction ledger.

Marshal sectors / mini-segments are DIFFERENT concepts (Phase-1 finding) and
are never mixed into these numbers; segment codes stay stored verbatim on
SectorTime rows for future mini-sector analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import Confidence, DerivedProvenance


@dataclass
class DriverSectorState:
    best: dict[int, float] = field(default_factory=dict)       # PB per sector
    best_lap: dict[int, int] = field(default_factory=dict)
    last: dict[int, float] = field(default_factory=dict)


@dataclass
class SectorClassification:
    sector_index: int
    time_s: float
    classification: str            # PURPLE | GREEN | YELLOW
    improved_personal_best: bool
    delta_to_pb_s: float | None    # negative = faster than prior PB
    session_best_holder: int | None


class SectorEngine:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.drivers: dict[int, DriverSectorState] = {}
        self.session_best: dict[int, tuple[float, int]] = {}   # sector -> (time, driver)

    def _driver(self, num: int) -> DriverSectorState:
        if num not in self.drivers:
            self.drivers[num] = DriverSectorState()
        return self.drivers[num]

    def fold_sector(self, *, driver_number: int, lap_number: int,
                    sector_index: int, time_s: float | None,
                    deleted: bool = False) -> SectorClassification | None:
        """Fold one completed sector; returns classification when applicable."""
        if deleted or time_s is None:
            return None
        d = self._driver(driver_number)
        prev_pb = d.best.get(sector_index)
        d.last[sector_index] = time_s

        if prev_pb is None or time_s < prev_pb:
            d.best[sector_index] = time_s
            d.best_lap[sector_index] = lap_number
            improved = True
        else:
            improved = False

        holder_entry = self.session_best.get(sector_index)
        if improved and (holder_entry is None or time_s < holder_entry[0]):
            self.session_best[sector_index] = (time_s, driver_number)

        current_holder = self.session_best.get(sector_index, (None, None))[1]
        if improved:
            classification = "PURPLE" if current_holder == driver_number else "GREEN"
        else:
            classification = "YELLOW"

        delta = (time_s - prev_pb) if prev_pb is not None else None
        return SectorClassification(
            sector_index=sector_index,
            time_s=time_s,
            classification=classification,
            improved_personal_best=improved,
            delta_to_pb_s=delta,
            session_best_holder=current_holder,
        )

    # ------------------------------------------------------- aggregates -----

    def personal_bests(self, driver_number: int) -> dict[int, float]:
        return dict(self._driver(driver_number).best)

    def theoretical_lap(self, driver_number: int) -> float | None:
        """Sum of the driver's three PBs; None when any sector is missing."""
        b = self.personal_bests(driver_number)
        vals = [b.get(i) for i in (1, 2, 3)]
        if any(v is None for v in vals):
            return None
        return sum(vals)  # type: ignore[misc]

    def theoretical_improvement(self, driver_number: int,
                                actual_best_s: float | None) -> float | None:
        theo = self.theoretical_lap(driver_number)
        if theo is None or actual_best_s is None:
            return None
        return actual_best_s - theo

    def session_best_holders(self) -> dict[int, tuple[float, int]]:
        return {k: v for k, v in sorted(self.session_best.items())}

    def best_possible_lap(self) -> float | None:
        """Fastest theoretical lap among drivers with complete sector sets."""
        candidates = [
            self.theoretical_lap(n) for n in self.drivers
            if self.theoretical_lap(n) is not None
        ]
        return min(candidates) if candidates else None

    # ------------------------------------------------------------ provenance

    @staticmethod
    def provenance_for(session_id: str, provider: str | None = None) -> DerivedProvenance:
        return DerivedProvenance(
            session_id=session_id,
            calculated_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc),
            source_provider=provider,
            confidence=Confidence.HIGH,
        )
