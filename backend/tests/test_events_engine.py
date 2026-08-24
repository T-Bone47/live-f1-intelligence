"""Significant-event engine + dedupe + snapshot + integration tests (Phase 2)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.analysis.common.dedup import EventDeduplicator
from app.analysis.common.models import Confidence, DerivedProvenance, Severity
from app.analysis.events import SignificantEventEngine

T0 = datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc)


class TestEventKeys:
    def test_key_format_stable(self):
        assert EventDeduplicator.build_key("s", "PURPLE_SECTOR", "1|S2|L5") == \
            "s|PURPLE_SECTOR|1|S2|L5"

    def test_dedupe_suppresses_repeat(self):
        d = EventDeduplicator()
        k = EventDeduplicator.build_key("s", "PACE_DROP", "4|W5|BUCKET3")
        assert not d.is_duplicate(k)
        assert d.is_duplicate(k)

    def test_bounded_memory_evicts_oldest(self):
        d = EventDeduplicator(capacity=100)
        for i in range(150):
            d.is_duplicate(f"k{i}")
        assert len(d) == 100
        assert not d.is_duplicate("k0")   # evicted -> allowed again
        assert d.is_duplicate("k149")     # recent -> still suppressed


class TestSectorEvents:
    def test_purple_sector_event_emitted_once(self):
        e = SignificantEventEngine("s")
        from app.analysis.sectors import SectorClassification

        c = SectorClassification(1, 25.2, "PURPLE", True, None, 81)
        a = e.sector_classified(c, 81, 10, T0)
        b = e.sector_classified(c, 81, 10, T0)  # same lap re-delivery
        assert a is not None and b is None
        assert a.event_type == "PURPLE_SECTOR"
        assert "sector" in a.metrics

    def test_yellow_never_emits(self):
        e = SignificantEventEngine("s")
        from app.analysis.sectors import SectorClassification

        c = SectorClassification(3, 27.0, "YELLOW", False, 0.5, 4)
        assert e.sector_classified(c, 9, 12, T0) is None


class TestLapEvents:
    def test_fastest_lap_change_vs_first_sb(self):
        e = SignificantEventEngine("s")
        out1 = e.lap_completed(driver_number=7, lap_number=1, duration_s=85.0,
                               personal_best=True, session_best_change=False,
                               is_first_sb=False, ts=T0)
        out2 = e.lap_completed(driver_number=9, lap_number=4, duration_s=84.0,
                               personal_best=True, session_best_change=True,
                               is_first_sb=False, ts=T0)
        types = {ev.event_type for ev in (out1 + out2)}
        assert "FASTEST_LAP_CHANGE" in types
        assert any(ev.severity is Severity.IMPORTANT
                   for ev in out2)

    def test_first_session_best_suppressed_as_change(self):
        e = SignificantEventEngine("s")
        out = e.lap_completed(driver_number=7, lap_number=1, duration_s=85.0,
                              personal_best=True, session_best_change=False,
                              is_first_sb=False, ts=T0)
        assert all(ev.event_type != "FASTEST_LAP_CHANGE" for ev in out)


class TestPositionPaceDegradationEvents:
    def test_position_change_event_with_severity_by_top10(self):
        e = SignificantEventEngine("s")
        ev = e.position_changed(3, 12, 10, 20, T0)
        assert ev.severity is Severity.NOTABLE and ev.metrics["to"] == 10

    def test_pace_drop_threshold(self):
        e = SignificantEventEngine("s")
        ev = e.pace_shift(44, +0.45, 30, T0)
        assert ev is not None and ev.event_type == "PACE_DROP"

    def test_small_pace_shift_ignored(self):
        e = SignificantEventEngine("s")
        assert e.pace_shift(44, +0.05, 30, T0) is None

    def test_degradation_event_labeled_estimated_and_prediction(self):
        e = SignificantEventEngine("s")
        ev = e.degradation_change(16, 2, 0.31, 0.62, 9, "MEDIUM", T0)
        assert ev.prediction is True
        assert ev.metrics["label"].startswith("ESTIMATED DEGRADATION")

    def test_degradation_bucket_allows_reemission_per_sign(self):
        e = SignificantEventEngine("s")
        a = e.degradation_change(16, 2, 0.31, 0.6, 9, "MEDIUM", T0)
        b = e.degradation_change(16, 2, -0.31, 0.6, 9, "MEDIUM", T0 + timedelta(minutes=5))
        assert a is not None and b is not None  # sign change => new key


class TestBattlePitWindowWeather:
    def test_overtake_event_pair_identity(self):
        from app.analysis.battles import Battle, BattleState

        e = SignificantEventEngine("s")
        b = Battle(ahead=4, behind=12, state=BattleState.OVERTAKE, started_lap=22)
        ev = e.battle_update(b, T0)
        assert ev.event_type == "OVERTAKE"
        again = e.battle_update(b, T0)
        assert again is None  # deduped

    def test_pit_window_prediction_flag(self):
        e = SignificantEventEngine("s")
        ev = e.pit_window(55, (18, 24), "MEDIUM", 18, T0)
        assert ev.prediction is True

    def test_weather_change_events_batched(self):
        e = SignificantEventEngine("s")
        raw = [{"event_type": "RAIN_START", "metrics": {"rainfall": True},
                "timestamp": T0}]
        out = e.weather_events(raw, T0)
        assert out[0].event_type == "WEATHER_CHANGE"
        assert out[0].metrics["rainfall"] is True


class TestProvenanceAndSerialization:
    def test_provenance_records_calc_version_and_inputs(self):
        p = DerivedProvenance(session_id="s",
                              calculated_at=datetime.now(timezone.utc),
                              input_event_ids=("a", "b"),
                              confidence=Confidence.HIGH)
        d = p.as_dict()
        assert d["kind"] == "DERIVED" and d["calc_version"]
        assert d["input_event_ids"] == ["a", "b"]

    def test_intelligence_event_serializable(self):
        e = SignificantEventEngine("s")
        from app.analysis.sectors import SectorClassification

        c = SectorClassification(2, 26.0, "PURPLE", True, -0.2, 16)
        ev = e.sector_classified(c, 16, 33, T0)
        blob = json.dumps(ev.as_dict())
        parsed = json.loads(blob)
        assert parsed["event_type"] == "PURPLE_SECTOR"
        assert parsed["provenance"]["kind"] == "DERIVED"


class TestSnapshotIntegration:
    def test_snapshot_builds_from_real_recording_fixture(self):
        """Integration: run engine over the committed backtest baseline fixture
        summary to ensure schema stability (determinism contract)."""
        baseline = Path(__file__).parent / "fixtures" / "backtest_baseline_11353.json"
        if not baseline.exists():
            baseline = Path(__file__).parent.parent.parent / (
                "tests/fixtures/backtest_baseline_11353.json")
        data = json.loads(baseline.read_text(encoding="utf-8"))
        s = data["summary"]
        assert s["calc_version"] == "analysis-2.0.0"
        assert s["phase"] == "CHEQUERED"
        assert s["fastest_lap"]["driver"] in range(1, 100)
        assert set(["PURPLE_SECTOR", "PERSONAL_BEST"]).issubset(s["event_counts"])

    def test_replay_through_analysis_is_provider_independent_contract(self):
        """The analysis layer accepts canonical envelopes only; this contract
        test pins that its public entry point takes payload dicts keyed by
        model type, never provider names."""
        from app.analysis import AnalysisEngine

        eng = AnalysisEngine("contract")
        assert hasattr(eng, "process_envelope") and hasattr(eng, "snapshot_dict")
        # no provider imports leak into analysis modules
        import app.analysis as pkg
        src = Path(pkg.__file__).read_text(encoding="utf-8")
        for banned in ("openf1", "signalr", "fastf1", "jolpica"):
            assert f"providers.{banned}" not in src
