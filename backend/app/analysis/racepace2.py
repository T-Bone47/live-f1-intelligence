"""Race pace intelligence 2.0 (Phase 5).

Builds on PaceEngine representative laps + clean-air classification +
StintEngine fits. Every metric carries confidence via the standard model.

RACE_PACE_2.md is normative. Key definitions:

- clean_air_pace(d)          mean of eligible laps with clean_air TRUE
- traffic_adjusted_pace(d)   mean eligible laps in traffic MINUS observed
                             traffic_loss (None when loss not measurable)
- tyre_adjusted_pace(d)      laps normalized to age 0 using ESTIMATED stint
                             degradation rates; mean across stints
- stint_normalized_pace      per-stint tyre-adjusted means
- field spread trend         rolling5 max-min slope over last K snapshots
                             -> CONVERGENCE (negative) / DIVERGENCE (positive)
- team/driver/field pace     group aggregates by team mapping
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import Confidence, mean, median
from app.analysis.confidence import assess_confidence
from app.analysis.laps import ClassifiedLap


@dataclass
class LapRecord:
    driver_number: int
    lap_number: int
    duration_s: float
    clean_air: str = "UNKNOWN"       # TRUE|FALSE|UNKNOWN
    traffic: str = "UNKNOWN"         # CLEAR|LIGHT|HEAVY|FOLLOWING|FOLLOWED|UNKNOWN
    stint_number: int | None = None
    tyre_age: int | None = None
    team_id: str | None = None


class RacePace2:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.laps: dict[int, list[LapRecord]] = {}
        self.field_spread_history: list[float] = []
        self.teams: dict[int, str] = {}

    # ---------------------------------------------------------------- fold --

    def fold_lap(self, rec: LapRecord) -> None:
        self.laps.setdefault(rec.driver_number, []).append(rec)

    def _driver_laps(self, driver_number: int) -> list[LapRecord]:
        return self.laps.setdefault(driver_number, [])

    def set_team(self, driver_number: int, team_id: str | None) -> None:
        if team_id:
            self.teams[driver_number] = team_id

    def _eligible(self, driver: int,
                  predicate=None) -> list[LapRecord]:
        rows = [r for r in self.laps.get(driver, []) if r.duration_s > 0]
        if predicate:
            rows = [r for r in rows if predicate(r)]
        return rows

    # -------------------------------------------------------------- paces --

    def clean_air_pace(self, driver: int) -> tuple[float | None, Confidence]:
        rows = [r.duration_s for r in
                self._eligible(driver, lambda r: r.clean_air == "TRUE")]
        a = assess_confidence(samples=len(rows), completeness=self._completeness(driver))
        return mean(rows), a.grade

    def traffic_adjusted_pace(self, driver: int) -> tuple[float | None, Confidence]:
        clean_rows = [r.duration_s for r in
                      self._eligible(driver, lambda r: r.clean_air == "TRUE")]
        traffic_rows = [r.duration_s for r in
                        self._eligible(driver, lambda r: r.traffic in ("LIGHT", "HEAVY"))]
        base_mean = mean(clean_rows)
        all_rows = [r.duration_s for r in self._eligible(driver)]
        if len(traffic_rows) >= 3 and base_mean is not None:
            loss = median(traffic_rows) - base_mean
            frac = len(traffic_rows) / max(len(all_rows), 1)
            adj = mean(all_rows) - max(loss, 0) * frac
            a = assess_confidence(samples=len(all_rows),
                                  fit_r2=None, cv=_cv(all_rows))
            return round(adj, 3), a.grade
        raw = [r.duration_s for r in self._eligible(driver)]
        a = assess_confidence(samples=len(raw), missing_inputs=not raw,
                              completeness=self._completeness(driver))
        return (round(mean(raw), 3) if raw else None), a.grade

    def tyre_adjusted_pace(self, driver: int,
                           degradation_by_stint: dict[int, float]) -> tuple[
            float | None, Confidence]:
        """Normalize each lap to age 0 via the stint's ESTIMATED linear rate."""
        normalized: list[float] = []
        n_total = 0
        for r in self._eligible(driver):
            rate = degradation_by_stint.get(r.stint_number or -1)
            if rate is None or r.tyre_age is None:
                continue
            normalized.append(r.duration_s - rate * r.tyre_age)
            n_total += 1
        a = assess_confidence(samples=n_total, fit_r2=0.5, missing_inputs=n_total == 0)
        return (round(mean(normalized), 3) if normalized else None), a.grade

    def stint_normalized(self, driver: int,
                         degradation_by_stint: dict[int, float]) -> dict[int, float]:
        out: dict[int, float] = {}
        stints = sorted({r.stint_number for r in self._eligible(driver)
                         if r.stint_number is not None})
        for sn in stints:
            rows = [r for r in self._eligible(driver) if r.stint_number == sn]
            rate = degradation_by_stint.get(sn)
            vals = [r.duration_s - (rate * (r.tyre_age or 0)) if rate is not None
                    else r.duration_s for r in rows]
            m = mean(vals)
            if m is not None:
                out[sn] = round(m, 3)
        return out

    # -------------------------------------------------- convergence etc ----

    def observe_field_spread(self, spread: float) -> str | None:
        """Track rolling-5 spread across drivers; returns event hint."""
        self.field_spread_history.append(round(spread, 4))
        k = self.field_spread_history[-8:]
        if len(k) < 8:
            return None
        half = len(k) // 2
        first, second = mean(k[:half]), mean(k[half:])
        delta = second - first
        if abs(delta) < 0.15:
            return None
        return "PACE_CONVERGENCE" if delta < 0 else "PACE_DIVERGENCE"

    # --------------------------------------------------------- group pace --

    def team_pace(self) -> dict[str, float]:
        by_team: dict[str, list[float]] = {}
        for num, team in self.teams.items():
            vals = [r.duration_s for r in self._eligible(num)]
            m = mean(vals)
            if m is not None:
                by_team.setdefault(team, []).append(m)
        return {t: round(mean(v), 3) for t, v in by_team.items()}

    def driver_pace(self) -> dict[int, float]:
        out = {}
        for num in self.laps:
            m = mean([r.duration_s for r in self._eligible(num)])
            if m is not None:
                out[num] = round(m, 3)
        return out

    def field_pace(self) -> float | None:
        meds = [median([r.duration_s for r in self._eligible(n)])
                for n in self.laps]
        meds = [m for m in meds if m is not None]
        return round(median(meds), 3) if meds else None

    def pace_gain_loss(self, driver: int, previous_window: float | None,
                       current_window: float | None) -> str | None:
        if previous_window is None or current_window is None:
            return None
        delta = current_window - previous_window
        if delta <= -0.3:
            return "PACE_GAIN"
        if delta >= 0.3:
            return "PACE_LOSS"
        return None

    @staticmethod
    def _completeness(driver: int) -> float:
        return 1.0  # v1: presence-based; refined when lap-count source exists


def _cv(values: list[float]) -> float | None:
    m = mean(values)
    if not values or not m:
        return None
    var = sum((v - m) ** 2 for v in values) / len(values)
    return (var ** 0.5) / m
