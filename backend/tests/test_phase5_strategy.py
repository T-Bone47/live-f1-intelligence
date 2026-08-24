"""Phase 5: strategy2, qualifying/practice intel, championship, packs."""

from __future__ import annotations

from app.analysis.strategy2 import StrategyEngine2
from app.analysis.sessions_intel import (
    PracticeIntel,
    QualifyingIntel,
)
from app.analysis.championship import project_from_order
from app.analysis.contextpacks import build_race_pack


class TestStrategyCandidates:
    def base(self, **over):
        kw = dict(compound="MEDIUM", tyre_age=12, degradation_rate=0.15,
                  base_pace=80.0, laps_remaining=30, pit_loss_s=22.0)
        kw.update(over)
        return StrategyEngine2().candidates(**kw)

    def test_ranked_candidates_exist(self):
        r = self.base()
        names = [c["strategy_rank"] for c in r["candidates"]]
        assert names == sorted(names) and len(names) >= 2

    def test_no_pit_loss_excludes_stop_strategies(self):
        r = self.base(pit_loss_s=None)
        assert all(c["stops"] == 0 for c in r["candidates"])

    def test_assumptions_always_present(self):
        r = self.base()
        for c in r["candidates"]:
            assert c["assumptions"], "every candidate documents assumptions"

    def test_sc_reduces_pit_loss(self):
        normal = self.base()
        sc = self.base(sc_active=True)
        one_n = next(c for c in normal["candidates"] if c["name"] == "ONE_STOP")
        one_s = next(c for c in sc["candidates"] if c["name"] == "ONE_STOP")
        assert one_s["pit_time_s"] < one_n["pit_time_s"]

    def test_confidence_never_arbitrary_high_without_data(self):
        r = self.base(degradation_rate=None)
        for c in r["candidates"]:
            assert c["confidence"] != "HIGH" or c["stops"] == 0


class TestPitWindow:
    def test_window_structure(self):
        w = StrategyEngine2().pit_window(compound="HARD", tyre_age=28,
                                         degradation_rate=0.05,
                                         laps_remaining=40)
        assert w["available"]
        assert w["earliest_window_lap"] <= min(w["best_window_range_laps"])
        assert w["latest_window_lap"] >= max(w["best_window_range_laps"])
        assert w["confidence"] in ("HIGH", "MEDIUM", "LOW", "NONE")

    def test_unknown_compound_unavailable(self):
        w = StrategyEngine2().pit_window(compound="UNKNOWN", tyre_age=5,
                                         degradation_rate=None,
                                         laps_remaining=30)
        assert not w["available"]

    def test_low_degradation_extends_latest(self):
        low = StrategyEngine2().pit_window(compound="HARD", tyre_age=10,
                                           degradation_rate=0.05, laps_remaining=None)
        high = StrategyEngine2().pit_window(compound="HARD", tyre_age=10,
                                            degradation_rate=0.30, laps_remaining=None)
        assert low["latest_window_lap"] > high["latest_window_lap"]


class TestUndercutOvercut:
    def test_undercut_available_with_evidence(self):
        u = StrategyEngine2().undercut(gap_to_ahead_s=1.8, closing_rate=-0.3,
                                       pit_loss_s=22.0, attacker_age=16,
                                       defender_age=24)
        assert u["undercut_available"] is True
        assert u["evidence"]["gap_to_ahead_s"] == 1.8

    def test_undercut_risk_when_defender_pulling_away(self):
        u = StrategyEngine2().undercut(gap_to_ahead_s=2.0, closing_rate=+0.4,
                                       pit_loss_s=22.0, attacker_age=20,
                                       defender_age=28)
        assert u["undercut_available"] is True and u["undercut_risk"] is True

    def test_undercut_unavailable_insufficient_state(self):
        u = StrategyEngine2().undercut(gap_to_ahead_s=None, closing_rate=None,
                                       pit_loss_s=22.0, attacker_age=None,
                                       defender_age=None)
        assert u["undercut_available"] is False

    def test_overcut_requires_car_in_pit(self):
        o = StrategyEngine2().overcut(gap_to_ahead_s=1.2, ahead_in_pit=True,
                                      ahead_tyre_age=10)
        assert o["overcut_available"] is True
        o2 = StrategyEngine2().overcut(gap_to_ahead_s=1.2, ahead_in_pit=False,
                                       ahead_tyre_age=10)
        assert o2["overcut_available"] is False


class TestSCOpportunity:
    def test_not_applicable_green_flag(self):
        s = StrategyEngine2().sc_opportunity(sc_or_vsc=False,
                                             window_open_now=True,
                                             pit_loss_normal_s=22.0,
                                             expected_rejoin_position=6)
        assert s["applicable"] is False

    def test_applicable_labels_opportunity_not_guarantee(self):
        s = StrategyEngine2().sc_opportunity(sc_or_vsc=True, window_open_now=True,
                                             pit_loss_normal_s=20.0,
                                             expected_rejoin_position=4)
        assert s["applicable"] is True
        assert s["cheap_pit_opportunity"] is True
        assert "not a guaranteed gain" in s["claim"]


class TestQualifyingIntel:
    def _feed(self):
        q = QualifyingIntel()
        # field of 6 drivers with improving boundary over observations
        times = {1: 80.0, 2: 80.5, 3: 81.0, 4: 81.5, 5: 82.0, 6: 83.0}
        return q, times

    def test_elimination_levels(self):
        q = QualifyingIntel()
        q.fold_best(1, 80.0, {})
        q.fold_best(2, 80.4, {})
        q.fold_best(3, 81.2, {})
        q.fold_best(4, None, {}) if False else None
        assert q.elimination_risk(1)["level"] == "SAFE"
        assert q.elimination_risk(2)["level"] == "ELEVATED"
        assert q.elimination_risk(3)["level"] == "HIGH"
        assert q.elimination_risk(9)["level"] == "UNKNOWN"

    def test_boundary_observation_and_cutoff_change(self):
        q = QualifyingIntel()
        assert q.observe_boundary(None) is None
        results = [q.observe_boundary(t) for t in (82.0, 81.7, 81.3)]
        assert any(r == "QUALIFYING_CUTOFF_CHANGE" for r in results)

    def test_projected_cutoff_needs_history(self):
        q = QualifyingIntel()
        v, conf = q.projected_cutoff()
        assert v is None and conf.value == "NONE"

    def test_theoretical_gain(self):
        q = QualifyingIntel()
        d = q.fold_best(5, 90.0, {1: 29.0, 2: 30.0, 3: 29.0})
        g = q.theoretical_gain(5)
        assert g == 2.0   # 90 - 88

    def test_evolution_gated(self):
        q = QualifyingIntel()
        assert q.track_evolution()["available"] is False


class TestPracticeIntel:
    def test_long_vs_short_segmentation(self):
        p = PracticeIntel()
        runs = p.fold_stint_laps(
            1, 1, [(i, 85.0 + i * 0.1) for i in range(10)], "HARD")
        kinds = {r.kind for r in runs}
        assert "LIKELY_LONG_RUN" in kinds
        short_runs = p.fold_stint_laps(
            1, 2, [(0, 82.0), (1, 82.1)], "SOFT")
        assert any(r.kind == "LIKELY_SHORT_RUN" for r in short_runs)

    def test_quali_sim_detected_on_near_best_cluster(self):
        p = PracticeIntel()
        p.note_session_best(80.0)
        laps = [(0, 80.25), (1, 80.30)] + [(i, 88.0) for i in range(2, 10)]
        runs = p.fold_stint_laps(1, 1, laps, "SOFT")
        assert any(r.kind == "LIKELY_QUALI_SIM" for r in runs)

    def test_race_sim_two_consistent_halves(self):
        p = PracticeIntel()
        laps = [(i, 85.0 if i < 10 else 85.2) for i in range(20)]
        runs = p.fold_stint_laps(1, 1, laps, "MEDIUM")
        assert any(r.kind == "LIKELY_RACE_SIM" for r in runs)

    def test_averages_and_team_aggregate(self):
        p = PracticeIntel()
        longs = [(i, 86.0 + i * 0.05) for i in range(10)]
        shorts = [(0, 82.0), (1, 82.05)]
        p.fold_stint_laps(1, 1, longs, "HARD")
        p.fold_stint_laps(1, 2, shorts, "SOFT")
        lr = p.long_run_average(1)
        sr = p.short_run_average(1)
        assert abs(lr - 86.225) < 0.01
        assert abs(sr - 82.025) < 0.01
        team = p.team_long_run([1])
        assert team == lr


class TestChampionship:
    STANDINGS = {
        "norris": {"points": 300, "constructor_ref": "mclaren", "position": 1},
        "verstappen": {"points": 280, "constructor_ref": "red-bull-racing",
                       "position": 2},
        "leclerc": {"points": 250, "constructor_ref": "ferrari", "position": 3},
    }

    def test_projection_deltas(self):
        order = [
            {"driver_ref": "norris", "family_name": "Norris", "position": 1},
            {"driver_ref": "verstappen", "family_name": "Verstappen", "position": 2},
            {"driver_ref": "leclerc", "family_name": "Leclerc", "position": 3},
        ]
        proj = project_from_order(current_order=order, standings=self.STANDINGS)
        norris = next(d for d in proj["drivers"] if d["driver"] == "Norris")
        assert norris["hypothetical_points_this_race"] == 25
        assert norris["projected_total"] == 325.0
        assert "HYPOTHETICAL" in norris["label"]

    def test_constructor_sums(self):
        order = [
            {"driver_ref": "norris", "family_name": "N", "position": 1},
            {"driver_ref": "leclerc", "family_name": "L", "position": 2},
        ]
        proj = project_from_order(current_order=order, standings=self.STANDINGS)
        c = proj["constructors_if_order_holds"]
        assert c["mclaren"] == 25
        assert c["ferrari"] == 18

    def test_position_out_of_points_scores_zero(self):
        order = [{"driver_ref": "norris", "family_name": "N", "position": 14}]
        proj = project_from_order(current_order=order, standings=self.STANDINGS)
        assert proj["drivers"][0]["hypothetical_points_this_race"] == 0


class TestContextPack:
    def test_race_pack_shape_and_bounded_facts(self):
        from app.analysis.contextpacks import build_race_pack as b

        snapshot = {
            "session_id": "openf1:x",
            "leaderboard": [{"position": 1, "driver_number": 1,
                             "personal_best_s": 74.3, "rolling5_s": 75.1,
                             "compound": "HARD", "tyre_age": 12}],
            "fastest_lap": {"driver": 16, "duration_s": 74.23, "at_lap": 60},
            "recent_events": [],
        }
        pack = b(snapshot=snapshot, degradation={"1": {"estimated_degradation_s_per_lap": 0.02}},
                 strategy={"candidates": []}, traffic={"states": {}},
                 battles=[], pace2=None)
        assert pack["pack"] == "race_v1"
        assert len(pack["facts"]) <= 40
        ids = [f["id"] for f in pack["facts"]]
        assert "fastest_lap" in ids and "lb1" in ids

    def test_fact_classes_are_provenance_tags(self):
        from app.analysis.contextpacks import _fact

        f = _fact("x", "D", "prediction-ish", confidence="LOW")
        assert f["class"] == "D" and f["confidence"] == "LOW"
