"""Phase 10.4 on the REAL Singapore pair (session 9161, #55 lap 19 vs #63 lap 16).

Production path: raw OpenF1 rows -> identity guard -> mapper -> 10.1B ->
10.1C -> 10.2 -> 10.4. Assertions are cross-checked against the RAW rows
(independent of the engine) or are structural invariants - never numbers
chosen because they look plausible. Skips without the fixture.
"""

from __future__ import annotations

import bisect
import itertools
import json
import os
from pathlib import Path

import pytest

from app.analysis.attribution import (
    AlignmentMode,
    AttributionStatus,
    attribute_comparison,
    report_to_dict,
)
from app.analysis.attribution_signals import detect_signals
from app.analysis.delta_analysis import SegmentKind, analyze_delta
from app.analysis.lap_comparison import compare_driver_laps
from app.providers.openf1.mapping import to_car_sample, to_lap
from app.providers.openf1.real_data import validate_rows_identity

ROOT = Path(__file__).parent.parent.parent
FIXTURE_DIR = Path(os.environ.get("REAL_PAIR_FIXTURE_DIR",
                                  ROOT / "scripts" / "fixtures" / "real-openf1-pair"))
EVIDENCE = ROOT / "docs" / "evidence" / "phase_10_4_singapore_attribution.json"

pytestmark = pytest.mark.skipif(not (FIXTURE_DIR / "meta.json").exists(),
                                reason="no real two-driver fixture")


def _load():
    meta = json.loads((FIXTURE_DIR / "meta.json").read_text())
    sid = f"openf1:{meta['session_key']}"
    raw, laps, samples = {}, {}, {}
    for d in (meta["driver_a"], meta["driver_b"]):
        lap_row = json.loads((FIXTURE_DIR / f"driver_{d}_lap.json").read_text())
        car = json.loads((FIXTURE_DIR / f"driver_{d}_car_data.json").read_text())
        validate_rows_identity(car, driver_number=d, session_key=meta["session_key"])
        validate_rows_identity([lap_row], driver_number=d, session_key=meta["session_key"])
        raw[d] = {"lap": lap_row, "car": sorted(car, key=lambda r: r["date"])}
        laps[d], _ = to_lap(lap_row, sid)
        samples[d] = sorted((to_car_sample(r, sid) for r in car), key=lambda s: s.ts)
    return meta, raw, laps, samples


def _run(a, b, meta, laps, samples):
    cmp = compare_driver_laps(laps[a], samples[a], None, laps[b], samples[b], None,
                              lap_length_m=meta["lap_length_m"])
    an = analyze_delta(cmp)
    return cmp, an, attribute_comparison(an, laps[a], laps[b])


@pytest.fixture(scope="module")
def real():
    meta, raw, laps, samples = _load()
    a, b = meta["driver_a"], meta["driver_b"]
    cmp, an, rep = _run(a, b, meta, laps, samples)
    return meta, raw, laps, samples, cmp, an, rep


def _dist_at_time(trace, t):  # independent of attribution._distance_at_time
    ts = [p.ts.timestamp() for p in trace.points]
    i = bisect.bisect_right(ts, t)
    p0, p1 = trace.points[i - 1], trace.points[i]
    return p0.distance_m + (t - ts[i - 1]) / (ts[i] - ts[i - 1]) * (p1.distance_m - p0.distance_m)


def test_uncertainty_is_the_misalignment_at_the_official_sector_lines(real):
    meta, raw, laps, _s, cmp, _an, rep = real
    a, b = meta["driver_a"], meta["driver_b"]
    u = rep.uncertainty
    assert u.source == "SECTOR_LINE_ANCHORS"
    expected = []
    for keys in (("duration_sector_1",), ("duration_sector_1", "duration_sector_2")):
        ta = laps[a].started_at.timestamp() + sum(raw[a]["lap"][k] for k in keys)
        tb = laps[b].started_at.timestamp() + sum(raw[b]["lap"][k] for k in keys)
        expected.append(_dist_at_time(cmp.trace_a, ta) - _dist_at_time(cmp.trace_b, tb))
    assert [x.misalignment_m for x in u.anchors] == pytest.approx(expected, abs=1e-9)
    assert u.misalignment_bound_m == pytest.approx(max(map(abs, expected)), abs=1e-12)
    assert rep.alignment_mode is AlignmentMode.NORMALIZED_DISTANCE


def test_official_sector_deltas_are_the_raw_lap_values_and_sum_to_the_lap(real):
    meta, raw, _l, _s, _c, _an, rep = real
    a, b = meta["driver_a"], meta["driver_b"]
    for sec in rep.sectors:
        k = f"duration_sector_{sec.sector}"
        assert sec.official_delta_s == pytest.approx(raw[a]["lap"][k] - raw[b]["lap"][k],
                                                     abs=1e-9)
    lap_delta = raw[a]["lap"]["lap_duration"] - raw[b]["lap"]["lap_duration"]
    assert rep.official_lap_delta_s == pytest.approx(lap_delta, abs=1e-9)
    assert sum(s.official_delta_s for s in rep.sectors) == pytest.approx(lap_delta, abs=1e-9)
    assert rep.sectors[2].engine_change_s is None  # finish not covered by telemetry


def test_segments_are_far_fewer_than_10_2_and_bounded_off_the_brakes(real):
    *_, cmp, an, rep = real
    data = [s for s in rep.segments if s.kind is not SegmentKind.NO_DATA]
    assert len(data) < len(an.segments) / 5  # 10.2 over-fragments (173)
    sig = {d: detect_signals(t) for d, t in (("a", cmp.trace_a), ("b", cmp.trace_b))}
    traces = {"a": cmp.trace_a, "b": cmp.trace_b}
    for s in data[:-1]:  # every interior boundary sits where neither driver brakes
        for k in ("a", "b"):
            i = bisect.bisect_right(sig[k].xs, s.x_end) - 1
            assert traces[k].points[i].brake_pct == 0


def test_brake_applications_match_the_raw_rows(real):
    meta, raw, *_rest, cmp, _an, _rep = real
    for d, trace in ((meta["driver_a"], cmp.trace_a), (meta["driver_b"], cmp.trace_b)):
        rows = raw[d]["car"]
        starts = sum(1 for r0, r1 in itertools.pairwise(rows) if r0["brake"] == 0 and r1["brake"] > 0)
        starts += 1 if rows[0]["brake"] > 0 else 0
        assert len(detect_signals(trace).brake_applications) == starts


def test_second_gear_is_only_driver_55_and_lands_in_the_right_segment(real):
    meta, raw, *_rest, cmp, _an, rep = real
    a, b = meta["driver_a"], meta["driver_b"]
    assert any(r["n_gear"] == 2 for r in raw[a]["car"])
    assert not any(r["n_gear"] == 2 for r in raw[b]["car"])
    xs2 = [p.normalized_distance for p in cmp.trace_a.points if p.gear == 2]
    for x in xs2:
        seg = next(s for s in rep.segments if s.x_start <= x <= s.x_end)
        assert seg.gear.min_a == 2 and seg.gear.min_b >= 3
    assert all(s.gear.min_b != 2 for s in rep.segments)


def test_accounting_reconciles_on_real_data(real):
    *_, an, rep = real
    acc = rep.accounting
    covered = [s.delta_t_s for s in an.samples if s.delta_t_s is not None]
    assert acc.actual_change_s == pytest.approx(covered[-1] - covered[0], abs=1e-12)
    total = sum(s.accumulated_change_s for s in rep.segments
                if s.accumulated_change_s is not None)
    assert total == pytest.approx(acc.actual_change_s, abs=1e-12)
    parts = (acc.attributed_change_s + acc.unattributed_significant_change_s
             + acc.below_significance_change_s)
    assert parts == pytest.approx(acc.actual_change_s, abs=1e-12)


def test_every_segment_change_is_exactly_the_10_2_curve_change(real):
    *_, an, rep = real
    for s in rep.segments:
        if s.accumulated_change_s is None:
            continue
        assert s.accumulated_change_s == (an.samples[s.end_index].delta_t_s
                                          - an.samples[s.start_index].delta_t_s)


def test_significance_labels_are_consistent_with_the_band(real):
    *_, rep = real
    for s in rep.segments:
        if s.kind is SegmentKind.NO_DATA:
            assert s.status is AttributionStatus.NO_DATA
            continue
        assert s.significant == (abs(s.accumulated_change_s) > s.uncertainty_s)
        if not s.significant:
            assert s.kind is SegmentKind.STABLE and s.primary_signal is None


def test_telemetry_ends_before_the_line_so_the_tail_is_no_data(real):
    *_, rep = real
    tail = rep.segments[-1]
    assert tail.kind is SegmentKind.NO_DATA and tail.accumulated_change_s is None
    assert tail.x_start == pytest.approx(rep.last_covered_x)


def test_swapping_the_real_drivers_negates_every_change(real):
    meta, _raw, laps, samples, _c, _an, rep = real
    _c2, _an2, rev = _run(meta["driver_b"], meta["driver_a"], meta, laps, samples)
    assert [(s.start_index, s.end_index) for s in rep.segments] == [
        (s.start_index, s.end_index) for s in rev.segments]
    for s, t in zip(rep.segments, rev.segments):
        if s.accumulated_change_s is not None:
            assert t.accumulated_change_s == pytest.approx(-s.accumulated_change_s, abs=1e-12)


def test_real_output_matches_the_committed_evidence(real):
    *_, rep = real
    if not EVIDENCE.exists():
        pytest.skip("evidence file not generated yet (scripts/attribution_report.py)")
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert committed["attribution"] == json.loads(json.dumps(report_to_dict(rep)))


def test_speed_and_throttle_are_integer_on_the_real_feed(real):
    # Evidence for SPEED_QUANTUM_KPH / THROTTLE_QUANTUM_PCT = 1 (quantization model).
    meta, raw, *_ = real
    for d in (meta["driver_a"], meta["driver_b"]):
        for r in raw[d]["car"]:
            assert float(r["speed"]).is_integer() and float(r["throttle"]).is_integer()


def test_per_car_throttle_calibration_is_flagged_not_hidden(real):
    # #55 sits at 99 on straights, #63 at 100: both "full", a calibration offset.
    *_, rep = real
    with_throttle = [s.throttle for s in rep.segments if s.throttle is not None]
    assert {(t.full_modal_a_pct, t.full_modal_b_pct) for t in with_throttle} == {(99.0, 100.0)}
    assert any("typical full-throttle value differs" in lim for lim in rep.limitations)


def test_real_throttle_lifts_hold_at_most_one_braking_zone(real):
    *_, cmp, _an, _rep = real
    for trace in (cmp.trace_a, cmp.trace_b):
        sig = detect_signals(trace)
        for lift in sig.throttle_lifts:
            onsets = [b for b in sig.brake_applications
                      if lift.lift.index <= b.onset.index < lift.end_index]
            assert len(onsets) <= 1
