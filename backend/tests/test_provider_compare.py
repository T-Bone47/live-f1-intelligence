"""Provider-comparison tests (Phase 7): MATCH/MISMATCH/MISSING semantics."""

from __future__ import annotations

from app.realtime.compare import compare_snapshots


def snap_a():
    return {
        "leaderboard": [
            {"driver_number": 1, "position": 1, "lap_number": 40,
             "last_lap_s": 74.9, "personal_best_s": 74.321,
             "compound": "HARD", "tyre_age": 24,
             "gap_to_leader_s": 0.0, "interval_s": 0.0},
            {"driver_number": 16, "position": 2, "lap_number": 40,
             "last_lap_s": 74.8, "personal_best_s": 74.230,
             "compound": "SOFT", "tyre_age": 15,
             "gap_to_leader_s": 1.2, "interval_s": 1.2},
        ],
        "fastest_lap": {"driver": 16, "duration_s": 74.230},
        "phase": "LIVE",
        "weather": {"air_temp_c": 19.1, "track_temp_c": 32.9,
                    "rainfall": False},
    }


def mutated(base):
    import copy

    s = copy.deepcopy(base)
    return s


class TestComparison:
    def test_identical_snapshots_all_match(self):
        out = compare_snapshots(snap_a(), snap_a())
        verdicts = {r.verdict for r in out.rows}
        assert "MISMATCH" not in verdicts
        assert out.summary()["match"] == len(out.rows)

    def test_position_mismatch_detected(self):
        b = mutated(snap_a())
        b["leaderboard"][0]["position"] = 3
        out = compare_snapshots(snap_a(), b)
        row = next(r for r in out.rows if r.key == "1.position")
        assert row.verdict == "MISMATCH"

    def test_missing_on_b(self):
        b = mutated(snap_a())
        b["leaderboard"] = b["leaderboard"][:1]  # driver 16 gone
        out = compare_snapshots(snap_a(), b)
        missing = [r for r in out.rows if r.verdict == "MISSING_ON_B"]
        assert any(r.key == "16" and r.domain == "leaderboard"
                   for r in missing)

    def test_missing_on_a(self):
        a = snap_a()
        b = mutated(a)
        a["leaderboard"] = [r for r in a["leaderboard"]
                            if r["driver_number"] != 1]
        out = compare_snapshots(a, b)
        missing_a = [r for r in out.rows if r.verdict == "MISSING_ON_A"]
        assert any(r.key == "1" for r in missing_a)

    def test_lap_time_tolerance(self):
        b = mutated(snap_a())
        b["leaderboard"][0]["last_lap_s"] = 74.94   # within 0.05? no: delta .04
        out = compare_snapshots(snap_a(), b)
        row = next(r for r in out.rows if r.key == "1.last_lap_s")
        assert row.verdict == "MATCH"   # 0.04 <= tol

    def test_symbolic_gap_never_fakes_numeric_match(self):
        b = mutated(snap_a())
        b["leaderboard"][1]["gap_to_leader_s"] = None
        out = compare_snapshots(snap_a(), b)
        row = next(r for r in out.rows if r.key == "16.gap_to_leader_s")
        # numeric None vs 1.2 -> MISSING_ON_B (honest), not zero-matched
        assert row.verdict == "MISSING_ON_B"

    def test_race_control_phase_comparison(self):
        b = mutated(snap_a())
        b["phase"] = "SAFETY_CAR"
        out = compare_snapshots(snap_a(), b)
        row = next(r for r in out.rows if r.domain == "race_control")
        assert row.verdict == "MISMATCH"

    def test_summary_counts(self):
        b = mutated(snap_a())
        b["phase"] = "SAFETY_CAR"
        out = compare_snapshots(snap_a(), b)
        s = out.summary()
        assert s["mismatch"] >= 1 and s["rows"] > 10
