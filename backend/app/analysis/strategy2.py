"""Strategy engine 2.0 (Phase 5): deterministic candidate strategies.

STRATEGY_ENGINE.md is normative. This engine produces RANKED CANDIDATES with
explicit assumptions and uncertainty - it never claims an "optimal" strategy.

Inputs (all from canonical state):
    current compound/age/stint fit, laps remaining, pit-loss estimate,
    traffic state, gaps, SC/VSC phase, available compounds.

Candidate model:
    stops in {0,1,2} (feasibility-filtered)
    segment time = laps * (base_pace + rate * avg_age)   [ESTIMATED]
    total = sum(segment times) + stops * pit_loss
    assumptions listed per candidate; confidence from degradation fit quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import Confidence
from app.analysis.confidence import assess_confidence

# DOCUMENTED ASSUMPTIONS (configurable):
BASELINE_LIFE = {"SOFT": 15, "MEDIUM": 25, "HARD": 35}
FRESH_TYRE_GAIN_S = 0.8        # assumed pace gain of fresh vs worn at age 0 baseline
SC_PIT_LOSS_FACTOR = 0.55      # SC lane loss fraction when no SC stop observed


@dataclass
class StrategyCandidate:
    name: str                      # ZERO_STOP | ONE_STOP | TWO_STOP | ALTERNATIVE_STINT
    rank: int
    estimated_total_s: float | None
    pit_time_s: float
    tyre_contribution_s: float | None
    stops: int
    confidence: Confidence
    assumptions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "strategy_rank": self.rank,
            "name": self.name,
            "estimated_total_s": self.estimated_total_s,
            "pit_time_s": round(self.pit_time_s, 2),
            "tyre_contribution_s": self.tyre_contribution_s,
            "stops": self.stops,
            "confidence": self.confidence.value,
            "assumptions": self.assumptions,
        }


class StrategyEngine2:
    def candidates(self, *, compound: str | None, tyre_age: int | None,
                   degradation_rate: float | None,
                   base_pace: float | None,
                   laps_remaining: int | None,
                   pit_loss_s: float | None,
                   sc_active: bool = False,
                   vsc_active: bool = False) -> dict:
        """Return ranked candidate strategies for ONE driver."""
        assumptions_common = [
            f"pit_loss={'observed ' + str(round(pit_loss_s, 1)) + 's' if pit_loss_s else 'UNAVAILABLE'}",
            "degradation linear within stint (see TYRE_INTELLIGENCE_2)",
            f"fresh-tyre gain assumption {FRESH_TYRE_GAIN_S}s",
        ]
        if sc_active or vsc_active:
            assumptions_common.append("SC/VSC active: reduced pit loss applies")
        if laps_remaining is None or tyre_age is None or compound is None:
            return {"candidates": [], "note": "insufficient state",
                    "assumptions": assumptions_common}

        eff_laps_remaining = max(laps_remaining, 1)
        loss = pit_loss_s if pit_loss_s is not None else 0.0
        if (sc_active or vsc_active) and pit_loss_s:
            loss = round(pit_loss_s * SC_PIT_LOSS_FACTOR, 2)
            assumptions_common.append(
                f"SC/VSC pit loss factor {SC_PIT_LOSS_FACTOR} (no SC stop observed)")

        rate = degradation_rate if degradation_rate is not None else 0.0
        base = base_pace if base_pace is not None else 0.0

        def segment_cost(laps: int, start_age: int, comp_life: int) -> tuple[float, list[str]]:
            a: list[str] = []
            usable = min(laps, max(comp_life - start_age, 3))
            overflow = laps - usable
            avg_age = start_age + usable / 2
            cost = usable * (base + rate * avg_age)
            if overflow > 0:
                cost += overflow * (base + rate * max(comp_life - start_age, 0)) \
                    + overflow * 1.5     # cliff penalty ASSUMPTION
                a.append(f"{overflow} laps beyond compound life penalized +1.5s/lap")
            return cost, a

        life = BASELINE_LIFE.get((compound or "").upper())
        raw: list[tuple[str, int, float | None, float, list[str]]] = []

        # ZERO_STOP
        c0, a0 = segment_cost(eff_laps_remaining, tyre_age, life or 25)
        raw.append(("ZERO_STOP", 0, c0, 0.0, a0))

        # ONE_STOP at each feasible window (quarter points of remaining laps)
        if pit_loss_s is not None:
            best_one = None
            for frac in (0.33, 0.5, 0.66):
                stop_lap = max(1, int(eff_laps_remaining * frac))
                first = stop_lap
                second = eff_laps_remaining - stop_lap
                c1, a1 = segment_cost(first, tyre_age, life or 25)
                fresh_gain = FRESH_TYRE_GAIN_S * first
                c1 -= fresh_gain
                c2, a2 = segment_cost(second, 0, life or 25)
                total = c1 + c2 + loss
                aa = a1 + a2
                if best_one is None or total < best_one[2]:
                    best_one = ("ONE_STOP", 1, total, loss, aa)
            if best_one:
                raw.append(best_one)

            # TWO_STOP (three equal-ish segments)
            seg = eff_laps_remaining / 3
            c_each, _ = segment_cost(int(seg), 0, life or 25)
            total2 = c_each * 2 + (eff_laps_remaining - 2 * int(seg)) * (
                base + rate * 4) + 2 * loss - FRESH_TYRE_GAIN_S * eff_laps_remaining
            raw.append(("TWO_STOP", 2, total2, 2 * loss,
                        ["assumes two fresh-tyre segments"]))

        scored = [(n, s, t, p, a) for (n, s, t, p, a) in raw if t is not None]
        scored.sort(key=lambda r: r[2])
        out: list[StrategyCandidate] = []
        for rank, (name, stops, total, pits, aa) in enumerate(scored, start=1):
            conf = assess_confidence(
                samples=12 if degradation_rate is not None else 0,
                completeness=0.9 if pit_loss_s is not None else 0.5,
                fit_r2=None).grade
            out.append(StrategyCandidate(
                name=name, rank=rank, estimated_total_s=round(total, 2),
                pit_time_s=pits,
                tyre_contribution_s=round(total - pits, 2) if total else None,
                stops=stops, confidence=conf,
                assumptions=assumptions_common + aa))
        return {"candidates": [c.as_dict() for c in out],
                "laps_remaining": eff_laps_remaining}

    # ------------------------------------------------------- pit windows ----

    def pit_window(self, *, compound: str | None, tyre_age: int | None,
                   degradation_rate: float | None,
                   laps_remaining: int | None,
                   traffic_state: str = "UNKNOWN") -> dict:
        if compound is None or tyre_age is None:
            return {"available": False,
                    "note": "compound/age unavailable"}
        life = BASELINE_LIFE.get(compound.upper())
        if life is None:
            return {"available": False,
                    "note": f"no window model for {compound}"}
        earliest = max(tyre_age, life - 6)
        latest = life + (6 if (degradation_rate or 0) < 0.15 else 2)
        if laps_remaining is not None:
            latest = min(latest, max(earliest, laps_remaining - 2))
        conf = assess_confidence(samples=(10 if degradation_rate is not None else 0),
                                 completeness=0.8).grade
        return {
            "available": True,
            "earliest_window_lap": earliest,
            "best_window_range_laps": [earliest + 2, max(earliest + 2, latest - 2)],
            "latest_window_lap": latest,
            "traffic_note": traffic_state if traffic_state != "UNKNOWN" else None,
            "confidence": conf.value,
            "assumptions": [
                f"baseline life {life} laps for {compound}",
                "latest extends when degradation < 0.15 s/lap",
            ],
        }

    # ------------------------------------------------------ undercut etc ----

    def undercut(self, *, gap_to_ahead_s: float | None, closing_rate: float | None,
                 pit_loss_s: float | None, attacker_age: int | None,
                 defender_age: int | None,
                 fresh_gain_s: float = FRESH_TYRE_GAIN_S) -> dict:
        evidence: dict = {}
        if gap_to_ahead_s is not None:
            evidence["gap_to_ahead_s"] = round(gap_to_ahead_s, 3)
        if closing_rate is not None:
            evidence["closing_rate_per_sample"] = closing_rate
        if pit_loss_s is not None:
            evidence["pit_loss_s"] = pit_loss_s
        if attacker_age is not None and defender_age is not None:
            evidence["tyre_delta_laps"] = attacker_age - defender_age

        core = (gap_to_ahead_s is not None and pit_loss_s is not None and
                gap_to_ahead_s <= UNDERCUT_GAP_MAX and attacker_age is not None and
                defender_age is not None and attacker_age + 4 <= defender_age)
        risk = bool(core and closing_rate is not None and closing_rate > 0.2)
        return {
            "undercut_available": core,
            "undercut_risk": risk,
            "evidence": evidence,
            "fresh_tyre_gain_assumption_s": fresh_gain_s,
        }

    def overcut(self, *, gap_to_ahead_s: float | None,
                ahead_in_pit: bool, ahead_tyre_age: int | None) -> dict:
        avail = bool(gap_to_ahead_s is not None and gap_to_ahead_s <= OVERCUT_GAP_MAX
                     and ahead_in_pit)
        risk = bool(avail and (ahead_tyre_age is not None and ahead_tyre_age <= 3))
        return {"overcut_available": avail, "overcut_risk": risk,
                "evidence": {"gap_to_ahead_s": gap_to_ahead_s,
                             "ahead_in_pit": ahead_in_pit,
                             "ahead_tyre_age": ahead_tyre_age}}

    # --------------------------------------------------------- SC/VSC -------

    def sc_opportunity(self, *, sc_or_vsc: bool, window_open_now: bool,
                       pit_loss_normal_s: float | None,
                       expected_rejoin_position: int | None) -> dict:
        if not sc_or_vsc:
            return {"applicable": False}
        cheap = bool(window_open_now)
        return {
            "applicable": True,
            "cheap_pit_opportunity": cheap,
            "estimated_pit_loss_s": round((pit_loss_normal_s or 0.0)
                                          * SC_PIT_LOSS_FACTOR, 2)
            if pit_loss_normal_s else None,
            "expected_rejoin_position": expected_rejoin_position,
            "position_gain_opportunity": (
                expected_rejoin_position is not None),
            "claim": "OPPORTUNITY INDICATOR - not a guaranteed gain",
        }


UNDERCUT_GAP_MAX = 2.5
OVERCUT_GAP_MAX = 1.8
