"""Pace engine tests (Phase 2): rolling windows, exclusions, trends, clean air."""

from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.laps import ClassifiedLap, LapClass, LapFlag
from app.analysis.pace import PaceEngine


def mk_lap(num, dur, *, cls=LapClass.REPRESENTATIVE, flags=None, stint=1):
    lap = ClassifiedLap(
        session_id="s", driver_number=1, lap_number=num,
        started_at=datetime(2026, 8, 23, 13, tzinfo=timezone.utc),
        duration_s=dur, sector_times_s=(None, None, None), stint_number=stint,
    )
    lap.lap_class = cls
    lap.flags = set(flags or [])
    lap.excluded_reasons = sorted(flags or []) if cls is not LapClass.REPRESENTATIVE else []
    return lap


class TestRollingWindows:
    def test_rolling3_mean(self):
        p = PaceEngine("s")
        for i, d in enumerate([90.0, 89.0, 88.0]):
            p.fold_classified(mk_lap(i + 1, d))
        assert p.rolling_pace(1, 3) == 89.0

    def test_rolling5_requires_full_window(self):
        p = PaceEngine("s")
        for i in range(4):
            p.fold_classified(mk_lap(i + 1, 90.0))
        assert p.rolling_pace(1, 5) is None

    def test_rolling5_slides(self):
        p = PaceEngine("s")
        for i, d in enumerate([91, 91, 91, 91, 91, 90, 90, 90, 90, 90]):
            p.fold_classified(mk_lap(i + 1, float(d)))
        assert p.rolling_pace(1, 5) == 90.0

    def test_excluded_laps_do_not_enter_windows(self):
        p = PaceEngine("s")
        p.fold_classified(mk_lap(1, 90.0))
        p.fold_classified(mk_lap(2, 120.0, cls=LapClass.OUTLIER,
                                 flags=[LapFlag.OUTLIER.value]))
        p.fold_classified(mk_lap(3, 90.0))
        p.fold_classified(mk_lap(4, 90.0))
        assert p.rolling_pace(1, 3) == 90.0

    def test_exclusion_reasons_recorded_not_discarded(self):
        p = PaceEngine("s")
        p.fold_classified(mk_lap(1, 130.0, cls=LapClass.INVALID,
                                 flags=[LapFlag.SAFETY_CAR.value]))
        assert p._driver(1).excluded[0][1] == ["SAFETY_CAR"]


class TestStintAndMedian:
    def test_stint_average_scoped(self):
        p = PaceEngine("s")
        for n, d in [(1, 90.0), (2, 89.5)]:
            p.fold_classified(mk_lap(n, d, stint=1))
        for n, d in [(20, 80.0)]:
            p.fold_classified(mk_lap(n, d, stint=2))
        p.attach_lap_object(mk_lap(1, 90.0, stint=1))
        p.attach_lap_object(mk_lap(2, 89.5, stint=1))
        p.attach_lap_object(mk_lap(20, 80.0, stint=2))
        assert p.stint_average(1, 1) == 89.75
        assert p.stint_average(1, 2) == 80.0

    def test_median_pace(self):
        p = PaceEngine("s")
        for n, d in enumerate([88.0, 89.0, 90.0, 200.0], start=1):
            if d < 100:
                p.fold_classified(mk_lap(n, d))
            else:
                p.fold_classified(mk_lap(n, d, cls=LapClass.OUTLIER,
                                         flags=["OUTLIER"]))
        assert p.median_pace(1) == 89.0


class TestTrend:
    def test_trend_improving_negative_slope(self):
        p = PaceEngine("s")
        data = [92.0, 91.6, 91.2, 90.8, 90.4]
        for i, d in enumerate(data):
            p.fold_classified(mk_lap(i + 1, d))
        assert p.pace_trend(1) < 0

    def test_trend_none_without_window(self):
        p = PaceEngine("s")
        for i in range(4):
            p.fold_classified(mk_lap(i + 1, 90.0))
        assert p.pace_trend(1) is None

    def test_field_delta(self):
        p = PaceEngine("s")
        for i in range(3):
            p.fold_classified(mk_lap(i + 1, 90.0))
            # second "driver"
            lap = mk_lap(i + 1, 91.0)
            lap.driver_number = 2
            p.fold_classified(lap)
        med = p.field_median()
        assert med == 90.5
        assert abs(p.pace_delta_to_field(1, med) + 0.5) < 1e-9


class TestCleanAir:
    def test_true_when_clear_both_sides(self):
        assert PaceEngine.classify_clean_air(3.0, 5.0) is not None and \
            PaceEngine.classify_clean_air(3.0, 5.0).value == "TRUE"

    def test_false_when_ahead_close(self):
        assert PaceEngine.classify_clean_air(0.8, 9.9).value == "FALSE"

    def test_false_when_behind_close(self):
        assert PaceEngine.classify_clean_air(4.0, 0.9).value == "FALSE"

    def test_unknown_in_gapless_zone(self):
        assert PaceEngine.classify_clean_air(1.5, 4.0).value == "UNKNOWN"

    def test_leader_has_no_car_ahead(self):
        assert PaceEngine.classify_clean_air(None, 3.0, is_leader=True).value == "TRUE"

    def test_no_data_unknown(self):
        assert PaceEngine.classify_clean_air(None, None).value == "UNKNOWN"


class TestThresholdsDocumented:
    def test_constants_exist(self):
        from app.analysis import pace as pace_mod

        assert hasattr(pace_mod, "TREND_WINDOW")
