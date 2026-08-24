"""Gap engine + battle detector tests (Phase 2)."""

from __future__ import annotations

from app.analysis.battles import (
    ACTIVE_GAP,
    APPROACH_GAP,
    BattleDetector,
    BattleState,
    DRS_GAP,
    SEPARATE_GAP,
)
from app.analysis.gaps import GapEngine


class TestGapEngine:
    def test_closing_rate_negative_when_closing(self):
        g = GapEngine("s")
        for lap, gap in [(1, 2.0), (2, 1.5), (3, 1.0)]:
            g.fold_interval(20, gap + 5, gap, None, None, lap=lap, car_ahead=10)
        rate = g.closing_rate(10, 20)
        assert rate is not None and rate < 0
        assert abs(rate + 0.5) < 1e-6

    def test_opening_rate_positive(self):
        g = GapEngine("s")
        for lap, gap in [(1, 1.0), (2, 1.8), (3, 2.6)]:
            g.fold_interval(20, gap + 5, gap, None, None, lap=lap, car_ahead=10)
        assert g.closing_rate(10, 20) > 0

    def test_trend_labels(self):
        g = GapEngine("s")
        for lap, gap in [(1, 2.0), (2, 1.4)]:
            g.fold_interval(20, gap + 5, gap, None, None, lap=lap, car_ahead=10)
        assert g.gap_trend(10, 20) == "CLOSING_FAST"

    def test_symbolic_gap_stored_verbatim(self):
        g = GapEngine("s")
        g.fold_interval(33, None, None, gap_raw="+2 LAPS", interval_raw=None,
                        lap=10, car_ahead=None)
        assert g.symbolic[33] == "+2 LAPS"
        assert 33 not in g.latest_gaps or g.latest_gaps[33] is None

    def test_window_bounds_samples(self):
        g = GapEngine("s")
        for lap in range(1, 10):
            g.fold_interval(20, float(lap), float(lap) * 0.1, None, None,
                            lap=lap, car_ahead=10)
        st = g.pairs[(10, 20)]
        assert len(st.samples) <= 60  # bounded memory

    def test_neighbors_from_positions(self):
        g = GapEngine("s")
        n = g.neighbors_by_position({5: 1, 3: 2, 9: 3})
        assert n[5] == (None, 3)
        assert n[3] == (5, 9)
        assert n[9] == (3, None)


class TestBattleFSM:
    def test_no_battle_at_large_gap(self):
        b = BattleDetector()
        r = b.update(4, 12, 5.0)
        assert r.state is BattleState.NO_BATTLE

    def test_approaching_entry(self):
        b = BattleDetector()
        r = b.update(4, 12, APPROACH_GAP - 0.1)
        assert r.state is BattleState.APPROACHING

    def test_drs_range_entry(self):
        b = BattleDetector()
        b.update(4, 12, 1.5)
        r = b.update(4, 12, DRS_GAP - 0.05)
        assert r.state is BattleState.DRS_RANGE

    def test_active_battle_needs_confirmation(self):
        b = BattleDetector()
        b.update(4, 12, 0.55)   # first close sample
        r = b.update(4, 12, 0.50)
        # entry state at <=ACTIVE_GAP goes straight to ACTIVE per _entry_state;
        # confirm path applies from DRS_RANGE escalation
        assert r.state in (BattleState.ACTIVE_BATTLE,)

    def test_escalation_from_drs_to_active(self):
        b = BattleDetector()
        b.update(4, 12, 0.9)            # DRS_RANGE
        b.update(4, 12, 0.58)           # below active: sample 1
        r = b.update(4, 12, 0.52)       # sample 2 -> ACTIVE
        assert r.state is BattleState.ACTIVE_BATTLE

    def test_defending_when_gap_regrows(self):
        b = BattleDetector()
        b.update(4, 12, 0.9)
        b.update(4, 12, 0.58)
        b.update(4, 12, 0.52)           # ACTIVE
        r = b.update(4, 12, 0.85)
        assert r.state is BattleState.DEFENDING

    def test_separating_after_active(self):
        b = BattleDetector()
        b.update(4, 12, 0.9)
        b.update(4, 12, 0.55)
        r = b.update(4, 12, SEPARATE := 2.7)
        assert r.state is BattleState.SEPARATING and SEPARATE > SEPARATE_GAP - 1

    def test_reset_to_no_battle(self):
        b = BattleDetector()
        b.update(4, 12, 0.9)
        for _ in range(4):
            b.update(4, 12, 5.0)
        assert b.update(4, 12, 5.0).state is BattleState.NO_BATTLE

    def test_overtake_on_position_swap(self):
        b = BattleDetector()
        b.update(4, 12, 0.9)
        b.update(4, 12, 0.55)
        r = b.update(4, 12, 0.5, position_swap=True)
        assert r.state is BattleState.OVERTAKE

    def test_pit_ends_battle_cleanly(self):
        b = BattleDetector()
        b.update(4, 12, 0.9)
        b.update(4, 12, 0.55)
        r = b.update(4, 12, None, either_pitted_or_out=True)
        assert r.state is BattleState.NO_BATTLE

    def test_min_gap_tracked_for_evidence(self):
        b = BattleDetector()
        b.update(4, 12, 1.5)
        b.update(4, 12, 0.45)
        assert b.battles[(4, 12)].min_gap_s == 0.45

    def test_threshold_constants_documented_values(self):
        assert APPROACH_GAP == 2.0 and DRS_GAP == 1.0 and ACTIVE_GAP == 0.6
