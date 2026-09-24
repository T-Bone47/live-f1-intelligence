"""Phase 10.2 REAL two-driver acceptance gate.

Needs a real fixture produced by scripts/fetch_real_driver_pair.py. Until
one exists this test SKIPS (it never falls back to synthetic data) - see
docs/PHASE_10_2_REAL_DATA_VALIDATION.md for why it could not be captured
from the build sandbox.

When the fixture exists, it runs the production path end to end:

    raw OpenF1 rows -> identity guard -> to_lap / to_car_sample
      -> build_lap_distance_trace -> normalize_lap        (10.1B)
      -> compare_driver_laps                              (10.1C)
      -> analyze_delta                                    (10.2)

and cross-checks results against values computed independently of those
engines (official lap times, a separate trapezoid integration, the raw
delta arrays).
"""

from __future__ import annotations

import json
import os
from itertools import pairwise
from pathlib import Path

import pytest

from app.analysis.common.models import Confidence
from app.analysis.delta_analysis import SegmentKind, analyze_delta
from app.analysis.lap_comparison import compare_driver_laps, delta_at
from app.analysis.lap_distance import MAX_GAP_S
from app.analysis.telemetry_integrity import telemetry_coverage
from app.core.enums import ProvenanceClass
from app.providers.openf1.mapping import to_car_sample, to_lap
from app.providers.openf1.real_data import validate_rows_identity

FIXTURE_DIR = Path(os.environ.get(
    "REAL_PAIR_FIXTURE_DIR",
    Path(__file__).parent.parent.parent / "scripts" / "fixtures" / "real-openf1-pair"))

pytestmark = pytest.mark.skipif(
    not (FIXTURE_DIR / "meta.json").exists(),
    reason=("no real two-driver fixture - run scripts/fetch_real_driver_pair.py "
            "outside a live F1 session (see docs/PHASE_10_2_REAL_DATA_VALIDATION.md)"),
)


def _load():
    meta = json.loads((FIXTURE_DIR / "meta.json").read_text())
    sid = f"openf1:{meta['session_key']}"
    sides = {}
    for d in (meta["driver_a"], meta["driver_b"]):
        lap_row = json.loads((FIXTURE_DIR / f"driver_{d}_lap.json").read_text())
        car_rows = json.loads((FIXTURE_DIR / f"driver_{d}_car_data.json").read_text())
        sides[d] = {"lap_row": lap_row, "car_rows": car_rows}
    return meta, sid, sides


@pytest.fixture(scope="module")
def real():
    meta, sid, sides = _load()
    for s in sides.values():
        s["lap"], _sectors = to_lap(s["lap_row"], sid)
        s["samples"] = sorted((to_car_sample(r, sid) for r in s["car_rows"]),
                              key=lambda x: x.ts)
    a, b = meta["driver_a"], meta["driver_b"]
    cmp = compare_driver_laps(sides[a]["lap"], sides[a]["samples"], None,
                               sides[b]["lap"], sides[b]["samples"], None,
                               lap_length_m=meta["lap_length_m"])
    return meta, sid, sides, cmp, analyze_delta(cmp)


def _trapezoid_m(car_rows: list[dict]) -> float:
    """Independent of app.analysis.lap_distance: plain trapezoid over raw rows."""
    from datetime import datetime
    rows = sorted(car_rows, key=lambda r: r["date"])
    total = 0.0
    for r0, r1 in pairwise(rows):
        if r0.get("speed") is None or r1.get("speed") is None:
            continue
        dt = (datetime.fromisoformat(r1["date"]) - datetime.fromisoformat(r0["date"])).total_seconds()
        if dt > 0:
            total += (r0["speed"] + r1["speed"]) / 2 / 3.6 * dt
    return total


def test_identity_two_different_drivers_same_session(real):
    meta, _sid, sides, cmp, _an = real
    assert meta["driver_a"] != meta["driver_b"]
    for d, s in sides.items():
        validate_rows_identity(s["car_rows"], driver_number=d, session_key=meta["session_key"])
        validate_rows_identity([s["lap_row"]], driver_number=d, session_key=meta["session_key"])
    assert (cmp.driver_a, cmp.driver_b) == (meta["driver_a"], meta["driver_b"])
    assert (cmp.lap_number_a, cmp.lap_number_b) == (meta["lap_a"], meta["lap_b"])


def test_telemetry_really_covers_each_lap(real):
    _meta, _sid, sides, _cmp, _an = real
    for s in sides.values():
        cov = telemetry_coverage(s["samples"])
        lap = s["lap"]
        assert cov["samples"] >= 50, "too few samples for a real lap"
        assert cov["monotonic"]
        assert cov["speed_valid_pct"] > 95.0
        # telemetry must start/end within one gap threshold of the official lap window
        assert (cov["first_ts"] - lap.started_at).total_seconds() <= MAX_GAP_S
        lap_end = lap.started_at.timestamp() + lap.duration_s
        assert lap_end - cov["last_ts"].timestamp() <= MAX_GAP_S
        assert all(smp.provenance.provenance_class == ProvenanceClass.B for smp in s["samples"])


def test_distance_engine_matches_independent_integration(real):
    meta, _sid, sides, cmp, _an = real
    for d, trace in ((meta["driver_a"], cmp.trace_a), (meta["driver_b"], cmp.trace_b)):
        assert trace.total_distance_m == pytest.approx(_trapezoid_m(sides[d]["car_rows"]), rel=1e-9)
        dist = [p.distance_m for p in trace.points]
        assert dist == sorted(dist)
        # plausibility vs the documented official length, not an invented target
        assert 0.9 <= trace.total_distance_m / meta["lap_length_m"] <= 1.1


def _independent_elapsed_at_m(car_rows: list[dict], target_m: float) -> float | None:
    """Independent of app.analysis.lap_distance: seconds from a driver's first
    sample until cumulative trapezoid distance first reaches target_m,
    linear in time within the crossing interval. None if never reached."""
    from datetime import datetime
    rows = sorted(car_rows, key=lambda r: r["date"])
    t0 = datetime.fromisoformat(rows[0]["date"])
    cum = 0.0
    if target_m <= 0:
        return 0.0
    for r0, r1 in pairwise(rows):
        ta, tb = datetime.fromisoformat(r0["date"]), datetime.fromisoformat(r1["date"])
        dt = (tb - ta).total_seconds()
        if dt <= 0 or r0.get("speed") is None or r1.get("speed") is None:
            continue
        step = (r0["speed"] + r1["speed"]) / 2 / 3.6 * dt
        if step > 0 and cum + step >= target_m:
            return (ta - t0).total_seconds() + dt * (target_m - cum) / step
        cum += step
    return None


@pytest.mark.parametrize("x", [0.25, 0.5, 0.75, 1.0])
def test_delta_matches_independent_recomputation(real, x):
    """Precision check: BOTH delta paths - 10.1C delta_at and 10.2's per-sample
    delta - must equal an independent recomputation from raw rows to float
    precision. No tolerance band."""
    meta, _sid, sides, cmp, an = real
    target = x * meta["lap_length_m"]
    ea = _independent_elapsed_at_m(sides[meta["driver_a"]]["car_rows"], target)
    eb = _independent_elapsed_at_m(sides[meta["driver_b"]]["car_rows"], target)
    sample = next(s for s in an.samples if abs(s.x - x) < 1e-12)
    if ea is None or eb is None:  # no data -> neither path may invent a delta
        assert sample.delta_t_s is None and delta_at(cmp, x) is None
    else:
        assert sample.delta_t_s == pytest.approx(ea - eb, abs=1e-6)  # 10.2
        assert delta_at(cmp, x) == pytest.approx(ea - eb, abs=1e-6)   # 10.1C


def test_finish_delta_is_plausible_against_official_lap_times(real):
    """Plausibility only (sign and rough size vs official timing), NOT a
    precision check - precision is test_delta_matches_independent_recomputation.
    Telemetry elapsed time starts at each first sample and integration drift
    moves where x=1.0 falls, so an exact match to official times is not
    expected; a disagreement beyond two gap thresholds is a red flag."""
    meta, _sid, sides, _cmp, an = real
    if an.delta_at_finish_s is None:
        pytest.skip("a trace stops short of x=1.0 - finish is honestly NO_DATA")
    official = (sides[meta["driver_a"]]["lap"].duration_s
                - sides[meta["driver_b"]]["lap"].duration_s)
    assert an.delta_at_finish_s == pytest.approx(official, abs=2 * MAX_GAP_S)


def test_delta_arrays_and_summary_are_internally_consistent(real):
    _meta, _sid, _sides, _cmp, an = real
    covered = [s for s in an.samples if s.delta_t_s is not None]
    assert covered, "no grid point where both drivers have data"
    for s in (covered[0], covered[len(covered) // 2], covered[-1]):
        assert s.delta_t_s == s.elapsed_a_s - s.elapsed_b_s          # sign convention
    ds = [s.delta_t_s for s in covered]
    if min(ds) < 0:
        assert an.max_gain_s == min(ds)
        assert an.max_gain_x == covered[ds.index(min(ds))].x
    else:
        assert an.max_gain_s is None
    if max(ds) > 0:
        assert an.max_loss_s == max(ds)
    else:
        assert an.max_loss_s is None


def test_segments_never_claim_gain_or_loss_without_data(real):
    _meta, _sid, _sides, _cmp, an = real
    for seg in an.segments:
        region = an.samples[seg.start_index:seg.end_index + 1]
        if seg.kind is SegmentKind.NO_DATA:
            assert seg.confidence == Confidence.NONE
            assert seg.time_change_s is None or any(s.delta_t_s is None for s in region)
        else:
            assert all(s.delta_t_s is not None for s in region)
    covered_change = sum(g.time_change_s for g in an.segments if g.kind is not SegmentKind.NO_DATA)
    first = next(s for s in an.samples if s.delta_t_s is not None)
    last = next(s for s in reversed(an.samples) if s.delta_t_s is not None)
    if not any(g.kind is SegmentKind.NO_DATA for g in an.segments):
        assert covered_change == pytest.approx(last.delta_t_s - first.delta_t_s, abs=1e-9)
