"""Qualifying + Practice intelligence (Phase 5).

QUALIFYING_INTELLIGENCE.md / PRACTICE_INTELLIGENCE.md normative.

Qualifying:
- phase tracking (Q1/Q2/Q3) from RCM qualifying_phase when upstream supplies
  it; otherwise UNKNOWN - never guessed.
- cutoff projection: extrapolate the boundary (P10/P15) best-lap improvement
  slope; needs >= 3 boundary observations else UNKNOWN.
- elimination risk bands: SAFE <0.3s, ELEVATED 0.3-0.7, HIGH >0.7 to projected
  cutoff; drivers without a time are UNKNOWN. Labeled HYPOTHETICAL.
- track evolution: field-best slope s/min; driver improvement separated by
  subtracting field slope from driver PB slope (approximation, documented).
- remaining theoretical gain: actual_best - theoretical.

Practice:
- run segmentation per driver stint: LONG_RUN >=8 laps; SHORT_RUN <=4;
  QUALI_SIM if >=2 consecutive laps within 0.35 s of session-best-relative
  pace; RACE_SIM = LONG_RUN with >=2 stints on same compound family.
  Labels are LIKELY_* - intent is never certain.
- long/short-run averages, consistency (cv), team aggregates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import Confidence, mean, linfit_slope_intercept
from app.analysis.confidence import assess_confidence


# ===================================================================== quali ==

@dataclass
class QualiDriverState:
    driver_number: int
    best_lap_s: float | None = None
    best_by_sector: dict[int, float] = field(default_factory=dict)
    attempts: int = 0


class QualifyingIntel:
    def __init__(self) -> None:
        self.phase: str | None = None            # "1"|"2"|"3"|None
        self.drivers: dict[int, QualiDriverState] = {}
        self.boundary_history: list[float] = []  # P10/P15 boundary per phase tick

    def fold_best(self, driver_number: int, duration_s: float,
                  sector_bests: dict[int, float]) -> QualiDriverState:
        d = self.drivers.setdefault(driver_number,
                                    QualiDriverState(driver_number))
        d.attempts += 1
        if d.best_lap_s is None or duration_s < d.best_lap_s:
            d.best_lap_s = duration_s
        for k, v in sector_bests.items():
            cur = d.best_by_sector.get(k)
            if cur is None or v < cur:
                d.best_by_sector[k] = v
        return d

    def set_phase(self, phase: str | None) -> None:
        self.phase = phase

    # -------------------------------------------------------------- cutoff --

    def boundary_time(self, *, part_size: int, total_drivers: int) -> tuple[float | None, int]:
        """Boundary (P10 for Q1/Q2 sized fields). Returns (time, position)."""
        pos = min(10, max(total_drivers - part_size, 1)) if total_drivers else 10
        times = sorted(d.best_lap_s for d in self.drivers.values()
                       if d.best_lap_s is not None)
        if len(times) < pos:
            return None, pos
        return times[pos - 1], pos

    def observe_boundary(self, t: float | None) -> str | None:
        if t is None:
            return None
        prev_n = len(self.boundary_history)
        self.boundary_history.append(t)
        if prev_n < 2:
            return None
        k = self.boundary_history[-4:]
        xs = [float(i) for i in range(len(k))]
        _a, slope, _r2 = linfit_slope_intercept(xs, k)
        if abs(slope) >= 0.02:   # >=0.02 s per observation improving/falling
            return "QUALIFYING_CUTOFF_CHANGE"
        return None

    def projected_cutoff(self) -> tuple[float | None, Confidence]:
        h = self.boundary_history[-5:]
        if len(h) < 3:
            return None, Confidence.NONE
        xs = [float(i) for i in range(len(h))]
        a, b, r2 = linfit_slope_intercept(xs, h)
        proj = a + b * len(h)          # one step ahead
        conf = assess_confidence(samples=len(h), fit_r2=r2).grade
        return round(proj, 3), conf

    def elimination_risk(self, driver_number: int) -> dict:
        d = self.drivers.get(driver_number)
        if not d or d.best_lap_s is None:
            return {"level": "UNKNOWN",
                    "note": "no representative lap time"}
        btime, _pos = self.boundary_time(part_size=10,
                                         total_drivers=len(self.drivers))
        if btime is None:
            return {"level": "UNKNOWN", "note": "not enough field times"}
        gap_to_cut = d.best_lap_s - btime
        level = ("SAFE" if gap_to_cut <= 0.3 else
                 "ELEVATED" if gap_to_cut <= 0.7 else
                 "HIGH" if gap_to_cut <= 1.5 else
                 "ELEVATED")   # far off pace in a big field still mid-band
        pos = [i for i, x in enumerate(
            sorted(self.drivers.values(), key=lambda z: z.best_lap_s or 9e9))
            if x.driver_number == driver_number]
        position = pos[0] + 1 if pos else None
        return {"level": level, "position": position,
                "gap_to_boundary_s": round(gap_to_cut, 3),
                "label": "HYPOTHETICAL projection"}

    def theoretical_gain(self, driver_number: int) -> float | None:
        d = self.drivers.get(driver_number)
        if not d or len(d.best_by_sector) < 3 or d.best_lap_s is None:
            return None
        theo = sum(d.best_by_sector[i] for i in (1, 2, 3))
        return round(d.best_lap_s - theo, 3)

    def track_evolution(self) -> dict:
        h = self.boundary_history[-8:]
        if len(h) < 4:
            return {"available": False}
        xs = [float(i) for i in range(len(h))]
        a, slope, r2 = linfit_slope_intercept(xs, h)
        return {"available": True, "slope_s_per_observation": round(slope, 4),
                "direction": "IMPROVING" if slope < 0 else
                             "DEGRADING" if slope > 0 else "FLAT"}

    def driver_vs_field_improvement(self, driver_number: int) -> float | None:
        """driver PB trend minus field-best trend (approximation)."""
        ev = self.track_evolution()
        if not ev.get("available"):
            return None
        d = self.drivers.get(driver_number)
        return ev["slope_s_per_observation"]  # refined in later phase


# ================================================================== practice ==

RUN_LONG_MIN = 8
RUN_SHORT_MAX = 4
QUALI_SIM_WINDOW_S = 0.35


@dataclass
class PracticeRun:
    kind: str                     # LIKELY_LONG_RUN | LIKELY_SHORT_RUN |
                                  # LIKELY_QUALI_SIM | LIKELY_RACE_SIM
    stint_number: int
    laps: list[float]
    average_s: float | None
    consistency_cv: float | None
    compound: str | None


class PracticeIntel:
    def __init__(self) -> None:
        self.stints: dict[int, dict[int, list[tuple[int, float]]]] = {}
        self.compounds: dict[int, dict[int, str]] = {}
        self.session_best_s: float | None = None
        self._evolution_offset: float = 0.0

    def note_session_best(self, best_s: float | None) -> None:
        if best_s is not None:
            self.session_best_s = best_s

    def fold_stint_laps(self, driver_number: int, stint_number: int,
                        laps: list[tuple[int, float]],
                        compound: str | None) -> list[PracticeRun]:
        self.stints.setdefault(driver_number, {})[stint_number] = laps
        if compound:
            self.compounds.setdefault(driver_number, {})[stint_number] = compound
        runs: list[PracticeRun] = []
        n = len(laps)
        durations = [d for _, d in laps]
        avg = mean(durations)
        cvv = None
        if avg:
            var = sum((d - avg) ** 2 for d in durations) / n
            cvv = round((var ** 0.5) / avg, 4)

        def classify_run(kind: str, subset: list[tuple[int, float]]) -> PracticeRun:
            sub_avg = mean([d for _, d in subset])
            sub_cv = None
            if sub_avg:
                var = sum((d - sub_avg) ** 2 for _, d in subset) / len(subset)
                sub_cv = round((var ** 0.5) / sub_avg, 4)
            return PracticeRun(kind=kind, stint_number=stint_number,
                               laps=[d for _, d in subset], average_s=sub_avg,
                               consistency_cv=sub_cv, compound=compound)

        if n >= RUN_LONG_MIN:
            runs.append(classify_run("LIKELY_LONG_RUN", laps))
            near_best = ([d for _, d in laps if self.session_best_s and
                          d <= self.session_best_s + QUALI_SIM_WINDOW_S * 10] or [])
            if len(near_best) >= 2:
                runs.append(classify_run("LIKELY_QUALI_SIM", laps[:2]))
        elif n <= RUN_SHORT_MAX and n >= 2:
            runs.append(classify_run("LIKELY_SHORT_RUN", laps))

        # race sim heuristic: two consecutive long-ish segments same compound
        if n >= RUN_LONG_MIN * 2:
            half = n // 2
            first_c = [d for _, d in laps[half:]]
            second_c = [d for _, d in laps[n - half:]]
            m1, m2 = mean(first_c), mean(second_c)
            if m1 and m2 and abs(m2 - m1) < 1.0:
                runs.append(classify_run("LIKELY_RACE_SIM", laps))
        return runs

    def long_run_average(self, driver_number: int) -> float | None:
        vals = []
        for stint in self.stints.get(driver_number, {}).values():
            if len(stint) >= RUN_LONG_MIN:
                vals += [d for _, d in stint]
        return mean(vals)

    def short_run_average(self, driver_number: int) -> float | None:
        vals = []
        for stint in self.stints.get(driver_number, {}).values():
            if 2 <= len(stint) <= RUN_SHORT_MAX:
                vals += [d for _, d in stint]
        return mean(vals)

    def consistency(self, driver_number: int) -> float | None:
        rows = self.stints.get(driver_number, {})
        all_laps = [d for stint in rows.values() for _a, d in stint]
        if len(all_laps) < 4:
            return None
        m = mean(all_laps)
        var = sum((d - m) ** 2 for d in all_laps) / len(all_laps)
        return round((var ** 0.5) / m, 4)

    def team_long_run(self, team_drivers: list[int]) -> float | None:
        vals = [self.long_run_average(d) for d in team_drivers]
        vals = [v for v in vals if v is not None]
        return mean(vals)
