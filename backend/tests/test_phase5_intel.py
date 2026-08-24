"""Phase 5 intelligence module tests: confidence, racepace2, tyres2, traffic."""

from __future__ import annotations

from app.analysis.common.models import Confidence
from app.analysis.confidence import assess_confidence
from app.analysis.racepace2 import LapRecord, RacePace2
from app.analysis.traffic import TrafficModel, TrafficState
from app.analysis.tyres2 import TyreIntelligence2


class TestConfidenceModel:
    def test_no_inputs_is_none_grade(self):
        a = assess_confidence(samples=0, missing_inputs=True)
        assert a.grade is Confidence.NONE and a.score == 0.0

    def test_strong_inputs_high(self):
        a = assess_confidence(samples=12, completeness=1.0, fit_r2=0.8,
                              cv=0.01, provider_reliability=0.95)
        assert a.grade is Confidence.HIGH and a.score >= 0.75

    def test_medium_band(self):
        a = assess_confidence(samples=5, completeness=0.7, fit_r2=0.4,
                              cv=0.04)
        assert a.grade is Confidence.MEDIUM

    def test_weak_inputs_low(self):
        a = assess_confidence(samples=1, completeness=0.3, fit_r2=0.05,
                              cv=0.09)
        assert a.grade in (Confidence.LOW, Confidence.NONE)

    def test_factors_are_measurable_not_arbitrary(self):
        a = assess_confidence(samples=10, completeness=1.0, fit_r2=0.6, cv=0.02)
        assert set(a.factors) >= {"samples", "completeness", "fit_r2",
                                  "consistency_score"}


def rec(driver, lap, dur, *, clean="TRUE", traffic="CLEAR", stint=1, age=None):
    return LapRecord(driver_number=driver, lap_number=lap, duration_s=dur,
                     clean_air=clean, traffic=traffic, stint_number=stint,
                     tyre_age=age)


class TestRacePace2:
    def test_fold_and_driver_pace(self):
        rp = RacePace2("s")
        rp.fold_lap(rec(1, 1, 90.0))
        rp.fold_lap(rec(1, 2, 91.0))
        assert rp.driver_pace()[1] == 90.5

    def test_clean_air_pace_uses_only_clean_laps(self):
        rp = RacePace2("s")
        rp.fold_lap(rec(1, 1, 88.0, clean="TRUE"))
        rp.fold_lap(rec(1, 2, 95.0, clean="FALSE"))
        pace, conf = rp.clean_air_pace(1)
        assert pace == 88.0
        assert conf.value in ("MEDIUM", "LOW")

    def test_traffic_adjusted_subtracts_measurable_loss(self):
        rp = RacePace2("s")
        for lap in range(1, 5):
            rp.fold_lap(rec(1, lap, 88.0, clean="TRUE"))
        for lap in range(5, 9):
            rp.fold_lap(rec(1, lap, 92.0, clean="FALSE", traffic="HEAVY"))
        adj, _conf = rp.traffic_adjusted_pace(1)
        # mean(all)=90 minus observed loss ~4 => back near clean pace
        assert adj is not None and abs(adj - 88.0) < 0.5

    def test_tyre_adjusted_normalizes_by_rate(self):
        rp = RacePace2("s")
        for i in range(6):
            rp.fold_lap(rec(1, i + 1, 80.0 + 0.5 * i, stint=1, age=i))
        adj, _conf = rp.tyre_adjusted_pace(1, {1: 0.5})
        assert abs(adj - 80.0) < 0.01

    def test_stint_normalized_separates_stints(self):
        rp = RacePace2("s")
        for i in range(5):
            rp.fold_lap(rec(1, i + 1, 85.0, stint=1, age=i))
        for i in range(5):
            rp.fold_lap(rec(1, 20 + i, 82.0, stint=2, age=i))
        sn = rp.stint_normalized(1, {})
        assert set(sn) == {1, 2}
        assert sn[2] < sn[1]

    def test_team_pace_aggregates(self):
        rp = RacePace2("s")
        rp.set_team(1, "mclaren"); rp.set_team(2, "mclaren"); rp.set_team(3, "ferrari")
        for lap in range(1, 4):
            rp.fold_lap(rec(1, lap, 90.0))
            rp.fold_lap(rec(2, lap, 92.0))
            rp.fold_lap(rec(3, lap, 89.0))
        tp = rp.team_pace()
        assert abs(tp["mclaren"] - 91.0) < 1e-6
        assert tp["ferrari"] == 89.0

    def test_gain_loss_thresholds(self):
        rp = RacePace2("s")
        assert rp.pace_gain_loss(1, 90.0, 89.5) == "PACE_GAIN"
        assert rp.pace_gain_loss(1, 89.5, 90.0) == "PACE_LOSS"
        assert rp.pace_gain_loss(1, 90.0, 90.1) is None

    def test_spread_convergence_divergence(self):
        rp = RacePace2("s")
        out = []
        for spread in [3.0] * 4 + [2.0] * 4:
            ev = rp.observe_field_spread(spread)
            if ev:
                out.append(ev)
        assert out[-1] == "PACE_CONVERGENCE"


class TestTyres2:
    def test_linear_fit_baseline(self):
        t = TyreIntelligence2()
        r = t.analyse(session_id="s", driver_number=1, stint_number=1,
                      compound="HARD",
                      laps=[(i, 80.0 + 0.1 * i) for i in range(10)])
        d = r.as_dict()
        assert abs(d["estimated_degradation"] - 0.1) < 0.01
        assert d["model_version"] == "tyres-2.0"

    def test_short_series_none(self):
        t = TyreIntelligence2()
        r = t.analyse(session_id="s", driver_number=1, stint_number=1,
                      compound="SOFT", laps=[(i, 80.0) for i in range(3)])
        assert r.degradation_rate_s_per_lap is None
        assert r.confidence is Confidence.NONE

    def test_warmup_detected(self):
        t = TyreIntelligence2()
        laps = [(0, 83.0), (1, 81.5), (2, 80.4)] + [(i, 80.0) for i in range(3, 10)]
        r = t.analyse(session_id="s", driver_number=1, stint_number=1,
                      compound="MEDIUM", laps=laps)
        assert r.warmup_laps == 3

    def test_cliff_requires_samples(self):
        t = TyreIntelligence2()
        short = [(i, 80.0 + 2.0 * i * i / 100) for i in range(6)]
        r = t.analyse(session_id="s", driver_number=1, stint_number=1,
                      compound="SOFT", laps=short)
        assert r.thermal_cliff == "UNKNOWN"   # n < 10 -> never claimed

    def test_cliff_detected_with_evidence(self):
        t = TyreIntelligence2()
        laps = []
        for i in range(14):
            base = 80.0 + 0.08 * i
            if i >= 9:
                base += (i - 8) ** 2 * 0.35
            laps.append((i, base))
        r = t.analyse(session_id="s", driver_number=1, stint_number=1,
                      compound="SOFT", laps=laps)
        assert r.thermal_cliff in ("DETECTED", "NOT_DETECTED")  # decided, not UNKNOWN
        assert r.n_samples >= CLIFF_N_MIN_SENTINEL


CLIFF_N_MIN_SENTINEL = 10


class TestTraffic:
    def test_state_matrix(self):
        tm = TrafficModel()
        assert tm.classify(gap_ahead_s=5.0, gap_behind_s=6.0).state is TrafficState.CLEAR
        assert tm.classify(gap_ahead_s=2.0, gap_behind_s=6.0).state is TrafficState.LIGHT
        assert tm.classify(gap_ahead_s=1.2, gap_behind_s=None).state is TrafficState.HEAVY
        assert tm.classify(gap_ahead_s=0.7, gap_behind_s=None).state is TrafficState.FOLLOWING
        assert tm.classify(gap_ahead_s=None, gap_behind_s=0.6).state is TrafficState.FOLLOWED

    def test_symbolic_gap_treated_clear_not_fake_close(self):
        tm = TrafficModel()
        a = tm.classify(gap_ahead_s=None, gap_behind_s=8.0, symbolic_ahead=True)
        assert a.state is TrafficState.CLEAR

    def test_insufficient_data_unknown(self):
        tm = TrafficModel()
        a = tm.classify(gap_ahead_s=None, gap_behind_s=None, has_any_gap_data=False)
        assert a.state is TrafficState.UNKNOWN and a.confidence is Confidence.NONE

    def test_pace_loss_gated_by_min_samples(self):
        tm = TrafficModel()
        tm.fold_lap(1, TrafficState.CLEAR, 88.0)
        tm.fold_lap(1, TrafficState.HEAVY, 93.0)
        loss, nt, nc = tm.pace_loss(1)
        assert loss is None and nt == 1 and nc == 1

    def test_pace_loss_computed_when_enough(self):
        tm = TrafficModel()
        for _ in range(3):
            tm.fold_lap(1, TrafficState.CLEAR, 88.0)
        for _ in range(3):
            tm.fold_lap(1, TrafficState.HEAVY, 91.5)
        loss, nt, nc = tm.pace_loss(1)
        assert loss is not None and abs(loss - 3.5) < 1e-6

    def test_recovery_tri_state(self):
        tm = TrafficModel()
        assert tm.recovered_after_traffic(1, [], None) is None
        assert tm.recovered_after_traffic(1, [88.0], None) is None
        assert tm.recovered_after_traffic(1, [88.1, 87.9], 88.0) is True
        assert tm.recovered_after_traffic(1, [90.1, 90.0], 88.0) is False
