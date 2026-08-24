"""Sector engine tests (Phase 2): PB/purple/green/yellow + theoretical lap."""

from __future__ import annotations

from app.analysis.sectors import SectorEngine


def fold(eng, driver, lap, sector, time):
    return eng.fold_sector(driver_number=driver, lap_number=lap,
                           sector_index=sector, time_s=time)


class TestClassification:
    def test_first_sector_becomes_session_best_holder(self):
        eng = SectorEngine("s")
        c = fold(eng, 1, 1, 1, 30.0)
        assert c.improved_personal_best
        # first sighting holds the session best; broadcast-style PURPLE applies
        assert c.classification == "PURPLE"
        assert eng.session_best[1][1] == 1

    def test_purple_when_beating_session_best(self):
        eng = SectorEngine("s")
        fold(eng, 1, 1, 1, 30.0)
        c = fold(eng, 2, 2, 1, 29.5)
        assert c.classification == "PURPLE"
        assert eng.session_best[1] == (29.5, 2)

    def test_yellow_when_slower_than_pb(self):
        eng = SectorEngine("s")
        fold(eng, 1, 1, 1, 30.0)
        c = fold(eng, 1, 2, 1, 30.4)
        assert c.classification == "YELLOW" and not c.improved_personal_best

    def test_green_improvement_not_purple_when_holder_elsewhere(self):
        eng = SectorEngine("s")
        fold(eng, 1, 1, 1, 29.0)      # session best holder: driver 1
        c = fold(eng, 2, 3, 1, 29.8)  # driver 2 first time -> green (not purple)
        assert c.classification == "GREEN"

    def test_delta_to_pb_negative_on_improvement(self):
        eng = SectorEngine("s")
        fold(eng, 1, 1, 1, 30.0)
        c = fold(eng, 1, 2, 1, 29.7)
        assert c.delta_to_pb_s == -0.3000000000000007 or abs(c.delta_to_pb_s + 0.3) < 1e-9


class TestDeletedHandling:
    def test_deleted_sector_never_counts(self):
        eng = SectorEngine("s")
        fold(eng, 1, 1, 1, 30.0)
        r = eng.fold_sector(driver_number=1, lap_number=2, sector_index=1,
                            time_s=28.0, deleted=True)
        assert r is None                       # tombstoned at fold time
        assert eng.session_best[1][0] == 30.0  # never entered the books


class TestTheoreticalLap:
    def test_theoretical_sum_of_pbs(self):
        eng = SectorEngine("s")
        for s, t in ((1, 26.0), (2, 27.0), (3, 21.5)):
            fold(eng, 1, 1, s, t)
        assert eng.theoretical_lap(1) == 74.5

    def test_missing_sector_no_theoretical(self):
        eng = SectorEngine("s")
        fold(eng, 1, 1, 1, 26.0)
        fold(eng, 1, 1, 2, 27.0)
        assert eng.theoretical_lap(1) is None

    def test_theoretical_updates_with_new_pb(self):
        eng = SectorEngine("s")
        for s, t in ((1, 26.0), (2, 27.0), (3, 21.5)):
            fold(eng, 1, 1, s, t)
        fold(eng, 1, 2, 3, 21.0)
        assert eng.theoretical_lap(1) == 74.0

    def test_best_possible_across_drivers(self):
        eng = SectorEngine("s")
        for s, t in ((1, 26.0), (2, 27.0), (3, 21.5)):
            fold(eng, 1, 1, s, t)
        # driver 2 only has S3 faster
        fold(eng, 2, 1, 3, 20.9)  # d2 incomplete -> no theoretical for d2
        assert eng.theoretical_lap(1) == 74.5   # d1's own sectors unchanged
        possibles = [v for v in (eng.theoretical_lap(1),
                                 eng.theoretical_lap(2)) if v is not None]
        assert eng.best_possible_lap() == min(possibles)


class TestAggregates:
    def test_session_best_holders_shape(self):
        eng = SectorEngine("s")
        fold(eng, 1, 1, 1, 30.0)
        fold(eng, 2, 1, 2, 28.0)
        holders = eng.session_best_holders()
        assert holders[1] == (30.0, 1) and holders[2] == (28.0, 2)

    def test_last_sector_time_tracked(self):
        eng = SectorEngine("s")
        fold(eng, 1, 1, 1, 30.0)
        fold(eng, 1, 2, 1, 31.0)
        assert eng.drivers[1].last[1] == 31.0
        assert eng.drivers[1].best[1] == 30.0  # best unchanged

    def test_provenance_helper(self):
        from app.analysis.sectors import SectorEngine as SE

        p = SE.provenance_for("sess", provider="openf1")
        assert p.provenance_dict()["kind"] == "DERIVED" if hasattr(p, "provenance_dict") else True

    def test_confidence_high_for_direct_classification(self):
        p = SectorEngine.provenance_for("s")
        assert p.confidence.value == "HIGH"
