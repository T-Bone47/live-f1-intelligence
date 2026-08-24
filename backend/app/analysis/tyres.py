"""Tyre / stint engine (Phase 2): stints, ages, pace-vs-age, degradation.

Design (verified against real recording ordering):

Providers may deliver stint records LONG after the laps they cover (Phase-1
recording: first stint record at event 136,815 of 1.07M). We therefore keep a
per-driver LAP LEDGER {lap_number: duration} and REASSIGN laps to stints
whenever a stint record arrives (lap_start/lap_end window). Final state
converges deterministically once all canonical events are folded - identical
input always yields identical assignments.

Degradation estimate (TYRE_DEGRADATION.md normative):

    pace(age) = base_pace + degradation_rate * age        [s per lap]

- Samples: laps inside one stint window, x = tyre age index, y = duration.
- Robustness: one MAD-outlier pass (2.5) before OLS.
- Minimum samples: 4 (else estimate stays None).
- Confidence: HIGH n>=8 & r2>=0.5; MEDIUM n>=5; LOW otherwise.
- ALWAYS labeled ESTIMATED DEGRADATION - never official data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import (
    Confidence,
    DerivedProvenance,
    linfit_slope_intercept,
    mad_outliers,
)
from app.core.enums import Compound
from app.core.models import TyreStint


@dataclass
class StintAnalysis:
    session_id: str
    driver_number: int
    stint_number: int
    compound: Compound = Compound.UNKNOWN
    lap_start: int | None = None
    lap_end: int | None = None
    laps: list[tuple[int, float]] = field(default_factory=list)  # (age, duration)

    base_pace_s: float | None = None
    degradation_rate_s_per_lap: float | None = None
    r_squared: float | None = None
    n_samples: int = 0
    n_excluded: int = 0
    confidence: Confidence = Confidence.NONE

    def fit_degradation(self) -> "StintAnalysis":
        xs_all = [float(a) for a, _d in self.laps]
        ys_all = [d for _a, d in self.laps]
        self.n_samples = len(ys_all)
        if len(ys_all) < 4:
            self.confidence = Confidence.NONE
            self.degradation_rate_s_per_lap = None
            return self
        outliers = set(mad_outliers(ys_all))
        xs = [x for i, x in enumerate(xs_all) if i not in outliers]
        ys = [y for i, y in enumerate(ys_all) if i not in outliers]
        self.n_excluded = len(outliers)
        self.n_samples = len(ys)
        a, b, r2 = linfit_slope_intercept(xs, ys)
        self.base_pace_s = round(a, 4)
        self.degradation_rate_s_per_lap = round(b, 4)
        self.r_squared = round(r2, 4)
        if len(ys) >= 8 and r2 >= 0.5:
            self.confidence = Confidence.HIGH
        elif len(ys) >= 5:
            self.confidence = Confidence.MEDIUM
        else:
            self.confidence = Confidence.LOW
        return self


class StintEngine:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.stints: dict[int, dict[int, StintAnalysis]] = {}
        self.current_stint: dict[int, int] = {}
        self._ledger: dict[int, dict[int, float]] = {}   # driver -> {lap: dur}

    # ---------------------------------------------------------------- fold --

    def note_lap(self, driver_number: int, lap_number: int,
                 duration_s: float | None) -> None:
        """Every classified-with-time lap lands in the ledger unconditionally;
        stint assignment happens (retroactively) when records arrive."""
        if duration_s is None:
            return
        self._ledger.setdefault(driver_number, {})[lap_number] = duration_s

    def fold_stint_record(self, stint: TyreStint) -> StintAnalysis:
        d = self.stints.setdefault(stint.driver_number, {})
        existing = d.get(stint.stint_number)
        if existing is None:
            existing = StintAnalysis(
                session_id=self.session_id,
                driver_number=stint.driver_number,
                stint_number=stint.stint_number,
                compound=stint.compound,
                lap_start=stint.lap_start,
                lap_end=stint.lap_end,
            )
            d[stint.stint_number] = existing
        else:
            if stint.compound is not Compound.UNKNOWN:
                existing.compound = stint.compound
            existing.lap_start = stint.lap_start or existing.lap_start
            existing.lap_end = stint.lap_end or existing.lap_end
        current = self.current_stint.get(stint.driver_number)
        if current is None or stint.stint_number >= current:
            self.current_stint[stint.driver_number] = stint.stint_number
        self.reassign_driver(stint.driver_number)
        return existing

    # ---------------------------------------------------------- assignment --

    def reassign_driver(self, driver_number: int) -> None:
        ledger = self._ledger.get(driver_number, {})
        for stint in self.stints.get(driver_number, {}).values():
            if stint.lap_start is None:
                continue
            end = stint.lap_end
            stint.laps = sorted(
                (ln - stint.lap_start, dur)
                for ln, dur in ledger.items()
                if stint.lap_start <= ln and (end is None or ln <= end)
            )

    # ------------------------------------------------------------- queries --

    def current(self, driver_number: int) -> StintAnalysis | None:
        n = self.current_stint.get(driver_number)
        return self.stints.get(driver_number, {}).get(n) if n is not None else None

    def tyre_age(self, driver_number: int, current_lap: int | None) -> int | None:
        s = self.current(driver_number)
        if s is None or s.lap_start is None or current_lap is None:
            return None
        return max(0, current_lap - s.lap_start)

    def compound(self, driver_number: int) -> Compound | None:
        s = self.current(driver_number)
        return s.compound if s else None

    def fit_driver_current(self, driver_number: int) -> StintAnalysis | None:
        self.reassign_driver(driver_number)
        s = self.current(driver_number)
        return s.fit_degradation() if s else None

    @staticmethod
    def compare_compounds(a: StintAnalysis, b: StintAnalysis) -> dict | None:
        if a.degradation_rate_s_per_lap is None or b.degradation_rate_s_per_lap is None:
            return None
        conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}
        return {
            "compound_a": a.compound.value,
            "compound_b": b.compound.value,
            "rate_delta_s_per_lap": round(
                b.degradation_rate_s_per_lap - a.degradation_rate_s_per_lap, 4),
            "base_pace_delta_s": round(
                b.base_pace_s - a.base_pace_s, 4),
            "confidence": min(a.confidence.value, b.confidence.value,
                              key=lambda c: conf_rank[c]),
            "unequal_samples": abs(a.n_samples - b.n_samples) > 3,
        }
