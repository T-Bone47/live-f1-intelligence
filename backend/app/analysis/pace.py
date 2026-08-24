"""Race-pace engine (Phase 2): rolling windows, stint pace, trends, clean air.

Method (PACE_METHODOLOGY.md is the normative text):

- Eligibility: a lap enters pace samples iff classified REPRESENTATIVE
  (exclusions recorded with reasons; nothing silently dropped).
- rolling_pace(N): mean of the driver's last N representative laps
  (chronological tail). None when fewer than N exist.
- stint_average: mean of all representative laps in the current stint.
- median_pace: median over the same eligibility rule.
- pace_trend: OLS slope (s/lap) across the trailing TREND_WINDOW (5)
  representative laps. Negative = improving.
- clean_air v1 thresholds (documented approximation):
    TRUE  : gap_to_ahead > 2.0 s AND gap_behind > 2.0 s (leader: ahead=None)
    FALSE : gap_to_ahead <= 1.0 s OR gap_behind <= 1.0 s
    UNKNOWN otherwise / no gap data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import CleanAir, Confidence, DerivedProvenance, mean, median, linfit_slope_intercept
from app.analysis.laps import ClassifiedLap

TREND_WINDOW = 5


@dataclass
class DriverPaceState:
    representative_laps: list[tuple[int, float]] = field(default_factory=list)  # (lap, s)
    excluded: list[tuple[int, list[str]]] = field(default_factory=list)


class PaceEngine:
    def __init__(self, session_id: str, trend_window: int = TREND_WINDOW) -> None:
        self.session_id = session_id
        self.trend_window = trend_window
        self.drivers: dict[int, DriverPaceState] = {}

    def _driver(self, num: int) -> DriverPaceState:
        if num not in self.drivers:
            self.drivers[num] = DriverPaceState()
        return self.drivers[num]

    # ---------------------------------------------------------------- fold --

    def fold_classified(self, lap: ClassifiedLap) -> None:
        d = self._driver(lap.driver_number)
        exclusions = lap.excluded_reasons or (
            [] if lap.duration_s is not None else ["NO_TIME"]
        )
        if lap.is_representative and lap.duration_s is not None:
            d.representative_laps.append((lap.lap_number, lap.duration_s))
            d.representative_laps.sort(key=lambda t: t[0])
        else:
            d.excluded.append((lap.lap_number, exclusions))

    # ------------------------------------------------------------- metrics --

    @staticmethod
    def _values(d: DriverPaceState, n: int | None = None,
                stint: int | None = None) -> list[float]:
        rows = d.representative_laps
        return [v for _, v in rows]

    def rolling_pace(self, driver_number: int, window: int) -> float | None:
        rows = self._driver(driver_number).representative_laps
        tail = [v for _, v in rows[-window:]]
        return mean(tail) if len(tail) == window else None

    def stint_average(self, driver_number: int, stint_number: int | None) -> float | None:
        """Mean of representative laps in the given stint (None = unknown)."""
        if stint_number is None:
            return None
        laps = getattr(self._driver(driver_number), "_lap_objects", [])
        vals = [l.duration_s for l in laps
                if l.stint_number == stint_number and l.duration_s is not None]
        return mean(vals)

    def attach_lap_object(self, lap: ClassifiedLap) -> None:
        """Keep classified objects for stint-scoped queries (memory-bounded by
        representative laps only)."""
        d = self._driver(lap.driver_number)
        if not hasattr(d, "_lap_objects"):
            d._lap_objects = []
        if lap.is_representative:
            d._lap_objects.append(lap)
            if len(d._lap_objects) > 400:
                d._lap_objects.pop(0)

    def median_pace(self, driver_number: int) -> float | None:
        return median(self._values(self._driver(driver_number)))

    def pace_trend(self, driver_number: int) -> float | None:
        rows = self._driver(driver_number).representative_laps[-self.trend_window:]
        if len(rows) < self.trend_window:
            return None
        xs = [float(i) for i in range(len(rows))]
        ys = [v for _, v in rows]
        _, slope, _r2 = linfit_slope_intercept(xs, ys)
        return slope

    def pace_delta_to_field(self, driver_number: int,
                            field_median: float | None) -> float | None:
        mine = self.median_pace(driver_number)
        if mine is None or field_median is None:
            return None
        return mine - field_median

    def field_median(self) -> float | None:
        meds = [median(d.representative_laps and
                       [v for _, v in d.representative_laps] or [])
                for d in self.drivers.values()]
        meds = [m for m in meds if m is not None]
        return median(meds)

    # ------------------------------------------------------------ clean air -

    @staticmethod
    def classify_clean_air(gap_ahead_s: float | None,
                           gap_behind_s: float | None,
                           is_leader: bool = False) -> CleanAir:
        AHEAD_CLEAR, CLOSE = 2.0, 1.0
        ahead_ok = True if is_leader else (
            gap_ahead_s is not None and gap_ahead_s > AHEAD_CLEAR
        )
        behind_ok = gap_behind_s is None or gap_behind_s > AHEAD_CLEAR
        close_any = (gap_ahead_s is not None and gap_ahead_s <= CLOSE) or (
            gap_behind_s is not None and gap_behind_s <= CLOSE)
        if close_any:
            return CleanAir.FALSE
        if ahead_ok and behind_ok:
            return CleanAir.TRUE
        return CleanAir.UNKNOWN

    # ---------------------------------------------------------- provenance --

    def provenance(self) -> DerivedProvenance:
        return DerivedProvenance(
            session_id=self.session_id,
            calculated_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc),
            confidence=Confidence.MEDIUM,
        )
