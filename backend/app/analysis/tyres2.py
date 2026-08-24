"""Tyre degradation 2.0 (Phase 5): warm-up, acceleration, thermal cliff.

Model (TYRE_INTELLIGENCE_2.md normative), model_version="tyres-2.0":

    lap_time(age) = a + b*age + c*age^2

- Linear coefficients (a,b) from the Phase-2 MAD+OLS fit remain the primary
  estimate; c (acceleration) is fitted only when n >= 8.
- warmup_laps: leading ages where lap time exceeds stint median by > WARMUP_T
  (0.3 s) before settling - reported as count, requires >= 4 samples.
- thermal_cliff: claimed ONLY when n >= 10 AND c >= CLIFF_C_MIN (0.02 s/lap^2)
  AND final-quarter mean exceeds first-quarter mean by >= CLIFF_DELTA_MIN
  (0.8 s). Otherwise explicitly UNKNOWN - we never claim a cliff without
  enough samples.

All outputs: ESTIMATED labels, sample counts, exclusions, limitations,
provenance DERIVED.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import Confidence, linfit_slope_intercept, median
from app.analysis.confidence import assess_confidence

MODEL_VERSION = "tyres-2.0"
WARMUP_THRESHOLD_S = 0.30
CLIFF_N_MIN = 10
CLIFF_C_MIN = 0.02          # s per lap^2
CLIFF_DELTA_MIN = 0.80      # s between quarter means


@dataclass
class TyreStint2Result:
    session_id: str
    driver_number: int
    stint_number: int
    compound: str | None
    base_pace_s: float | None = None
    degradation_rate_s_per_lap: float | None = None
    acceleration_s_per_lap2: float | None = None
    warmup_laps: int | None = None
    thermal_cliff: str = "UNKNOWN"      # DETECTED | NOT_DETECTED | UNKNOWN
    n_samples: int = 0
    n_excluded: int = 0
    r_squared: float | None = None
    confidence: Confidence = Confidence.NONE
    model_version: str = MODEL_VERSION
    limitations: tuple[str, ...] = (
        "linear+quadratic fit on representative laps",
        "no fuel/track-evolution correction",
        "thermal cliff requires n>=10 and acceleration evidence",
    )

    def as_dict(self) -> dict:
        return {
            "model_version": self.model_version,
            "estimated_degradation": self.degradation_rate_s_per_lap,
            "base_pace": self.base_pace_s,
            "acceleration_s_per_lap2": self.acceleration_s_per_lap2,
            "warmup_laps": self.warmup_laps,
            "thermal_cliff": self.thermal_cliff,
            "sample_count": self.n_samples,
            "excluded_laps": self.n_excluded,
            "confidence": self.confidence.value,
            "r_squared": self.r_squared,
            "limitations": list(self.limitations),
            "label": "ESTIMATED DEGRADATION - not official data",
        }


def _quad_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Least squares y = a + b x + c x^2 via normal equations (3x3)."""
    n = len(xs)
    s = lambda v: sum(v)  # noqa: E731
    Sx, Sx2, Sx3, Sx4 = s(xs), s(x * x for x in xs), s(x ** 3 for x in xs), s(x ** 4 for x in xs)
    Sy, Sxy, Sx2y = s(ys), s(x * y for x, y in zip(xs, ys)), \
        s((x * x) * y for x, y in zip(xs, ys))
    # solve [[n,Sx,Sx2],[Sx,Sx2,Sx3],[Sx2,Sx3,Sx4]] * [a,b,c] = [Sy,Sxy,Sx2y]
    import copy

    m = [[float(n), Sx, Sx2, Sy],
         [Sx, Sx2, Sx3, Sxy],
         [Sx2, Sx3, Sx4, Sx2y]]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda rr: abs(m[rr][col]))
        if abs(m[pivot][col]) < 1e-12:
            return 0.0, 0.0, 0.0
        m[col], m[pivot] = m[pivot], m[col]
        for rr in range(3):
            if rr == col:
                continue
            f = m[rr][col] / m[col][col]
            for cc in range(col, 4):
                m[rr][cc] -= f * m[col][cc]
    a = m[0][3] / m[0][0]
    b = m[1][3] / m[1][1]
    c = m[2][3] / m[2][2]
    return a, b, c


class TyreIntelligence2:
    def analyse(self, *, session_id: str, driver_number: int, stint_number: int,
                compound: str | None,
                laps: list[tuple[int, float]]) -> TyreStint2Result:
        """laps: (tyre_age_index, duration). Expects pre-filtered clean laps."""
        res = TyreStint2Result(session_id=session_id, driver_number=driver_number,
                               stint_number=stint_number, compound=compound)
        ages_all = [float(a) for a, _d in laps]
        times_all = [d for _a, d in laps]
        res.n_samples = len(times_all)
        if len(times_all) < 4:
            res.confidence = Confidence.NONE
            return res

        med = median(times_all) or 0.0
        warm = 0
        for age, t in sorted(zip(ages_all, times_all)):
            if t - med > WARMUP_THRESHOLD_S and age <= 3:
                warm += 1
            else:
                break
        res.warmup_laps = warm if len(times_all) >= 4 else None

        a, b, _r2 = linfit_slope_intercept(ages_all, times_all)
        res.base_pace_s = round(a, 3)
        res.degradation_rate_s_per_lap = round(b, 4)
        res.r_squared = round(_r2 or 0.0, 4)

        if len(times_all) >= 8:
            qa, qb, qc = _quad_fit(ages_all, times_all)
            res.acceleration_s_per_lap2 = round(qc, 5)

            if len(times_all) >= CLIFF_N_MIN and qc >= CLIFF_C_MIN:
                k = max(2, len(times_all) // 4)
                ordered = [t for _age, t in sorted(zip(ages_all, times_all))]
                q1 = sum(ordered[:k]) / k
                q4 = sum(ordered[-k:]) / k
                res.thermal_cliff = ("DETECTED" if (q4 - q1) >= CLIFF_DELTA_MIN
                                     else "NOT_DETECTED")
            else:
                res.thermal_cliff = "UNKNOWN"

        conf = assess_confidence(samples=res.n_samples, fit_r2=res.r_squared)
        res.confidence = conf.grade
        return res
