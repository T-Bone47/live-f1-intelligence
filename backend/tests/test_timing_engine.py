"""Timing engine tests (Phase 2 minimum 10+)."""

from __future__ import annotations

from app.analysis.timing import TimingEngine


def mk(session="s"):
    return TimingEngine(session)


class TestLapFolding:
    def test_pb_set_on_first_valid_lap(self):
        t = mk()
        r = t.fold_lap(driver_number=1, lap_number=1, duration_s=90.0, deleted=False)
        assert r["personal_best"] is True
        d = t.state.driver(1)
        assert d.personal_best_s == 90.0 and d.last_lap_s == 90.0

    def test_pb_improves_only_when_faster(self):
        t = mk()
        t.fold_lap(driver_number=1, lap_number=1, duration_s=90.0, deleted=False)
        r = t.fold_lap(driver_number=1, lap_number=2, duration_s=91.0, deleted=False)
        assert r["personal_best"] is False
        d = t.state.driver(1)
        assert d.previous_lap_s == 90.0 and d.last_lap_s == 91.0

    def test_previous_lap_tracked(self):
        t = mk()
        t.fold_lap(driver_number=1, lap_number=1, duration_s=90.0, deleted=False)
        t.fold_lap(driver_number=1, lap_number=2, duration_s=89.0, deleted=False)
        d = t.state.driver(1)
        assert d.previous_lap_s == 90.0 and d.last_lap_s == 89.0

    def test_deleted_retracts_pb(self):
        t = mk()
        t.fold_lap(driver_number=1, lap_number=5, duration_s=80.0, deleted=False)   # becomes PB
        r = t.fold_lap(driver_number=1, lap_number=5, duration_s=80.0, deleted=True)
        assert r == {"retracted": True}
        assert t.state.driver(1).personal_best_s is None

    def test_null_duration_neither_pb_nor_last(self):
        t = mk()
        r = t.fold_lap(driver_number=1, lap_number=1, duration_s=None, deleted=False)
        assert r is None
        d = t.state.driver(1)
        assert d.lap_number == 1 and d.last_lap_s is None


class TestSessionBest:
    def test_first_sb_is_not_a_change(self):
        t = mk()
        r = t.fold_lap(driver_number=7, lap_number=1, duration_s=85.0, deleted=False)
        assert r["session_best"] is False  # first holder isn't a change event

    def test_sb_change_detected(self):
        t = mk()
        t.fold_lap(driver_number=7, lap_number=1, duration_s=85.0, deleted=False)
        r = t.fold_lap(driver_number=9, lap_number=3, duration_s=84.5, deleted=False)
        assert r["session_best"] is True
        assert t.state.session_best_driver == 9
        assert t.state.fastest_lap_changed_at_lap == 3

    def test_slower_lap_no_sb_change(self):
        t = mk()
        t.fold_lap(driver_number=7, lap_number=1, duration_s=85.0, deleted=False)
        r = t.fold_lap(driver_number=9, lap_number=3, duration_s=86.0, deleted=False)
        assert r["session_best"] is False


class TestPositions:
    def test_position_change_delta(self):
        t = mk()
        assert t.fold_position(1, "t", 3) is None  # first sighting
        delta = t.fold_position(1, "t", 2)
        assert delta == 1  # gained one place
        d = t.state.driver(1)
        assert d.previous_position == 3 and d.position == 2

    def test_same_position_no_event(self):
        t = mk()
        t.fold_position(1, "t", 4)
        assert t.fold_position(1, "t", 4) is None


class TestIntervalsAndSymbolicGaps:
    def test_numeric_gap_stored_and_history_kept(self):
        t = mk()
        d = t.state.driver(1)
        TimingEngine.apply_interval_sample(d, 3.2, 0.8, lap=5)
        assert d.gap_to_leader_s == 3.2 and d.interval_s == 0.8
        assert d.gap_history == [(5, 3.2)]

    def test_symbolic_gap_never_converted(self):
        t = mk()
        d = t.state.driver(1)
        TimingEngine.apply_interval_sample(d, "+1 LAP", 12.5, lap=6)
        assert d.gap_to_leader_s is None          # no fake seconds
        assert d.gap_to_leader_raw == "+1 LAP"    # raw preserved
        assert d.gap_history == []                # excluded from numeric series

    def test_gap_evolution_series(self):
        t = mk()
        d = t.state.driver(1)
        for lap, g in [(1, 5.0), (2, 4.0), (3, 3.0)]:
            TimingEngine.apply_interval_sample(d, g, g - 2, lap=lap)
        assert [g for _, g in d.gap_history] == [5.0, 4.0, 3.0]


class TestPitRetiredFlags:
    def test_pit_flag_roundtrip(self):
        t = mk()
        t.mark_pit(4, True)
        assert t.state.driver(4).in_pit is True
        t.mark_pit(4, False)
        assert t.state.driver(4).in_pit is False

    def test_retirement_clears_pit(self):
        t = mk()
        t.mark_pit(4, True)
        t.mark_retired(4)
        d = t.state.driver(4)
        assert d.retired is True and d.in_pit is False
