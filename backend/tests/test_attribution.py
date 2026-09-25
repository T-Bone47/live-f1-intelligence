"""Phase 10.4 attribution engine - mechanics on SYNTHETIC ground truth.

Every scenario changes one known thing between A and B (braking point,
throttle application, gear, DRS, ...) and asserts the engine reports
exactly that - and nothing it was not given. Real-data behaviour lives in
tests/test_attribution_real_pair.py.
"""

from __future__ import annotations

import json

import pytest
from synthetic_lap import make_lap, two_corner_profile

from app.analysis.attribution import (
    AlignmentMode,
    AlignmentUncertainty,
    AttributionStatus,
    attribute_comparison,
    attribution_facts,
    report_to_dict,
)
from app.analysis.delta_analysis import SegmentKind, analyze_delta
from app.analysis.lap_comparison import compare_driver_laps

L = 2000.0
# B brakes 50 m later into corner 1. 50 m, not 20: at 3.7 Hz and 300 kph the
# real samples are ~22.5 m apart, so a 20 m onset difference is NOT resolvable
# from the brake channel alone (both onset brackets overlap) - the engine must
# say so rather than claim it.
LATE_BRAKE_C1 = {
    "speed_knots": [(0, 280), (500, 300), (550, 300), (600, 100), (650, 100), (900, 290),
                 (1300, 300), (1380, 150), (1420, 150), (1650, 290), (2000, 295)],
    "brake": [(550, 600), (1300, 1380)]}


def _report(prof_a, prof_b, uncertainty=None, trim_a_m=None):
    lap_a, sa = make_lap(prof_a, 1)
    lap_b, sb = make_lap(prof_b, 2)
    if trim_a_m is not None:  # telemetry stops early: coverage gap at the end
        keep = int(len(sa) * trim_a_m / L)
        sa = sa[:keep]
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    return attribute_comparison(analyze_delta(cmp), lap_a, lap_b, uncertainty=uncertainty)


def _seg_at(report, metres):
    x = metres / L
    return next(s for s in report.segments if s.x_start <= x <= s.x_end)


def test_identical_laps_produce_no_gain_or_loss_and_no_attribution():
    r = _report(two_corner_profile(), two_corner_profile())
    assert all(s.kind in (SegmentKind.STABLE, SegmentKind.NO_DATA) for s in r.segments)
    assert all(s.accumulated_change_s == 0 for s in r.segments
               if s.accumulated_change_s is not None)
    assert r.accounting.attributed_change_s == 0
    assert all(s.status is AttributionStatus.NOT_SIGNIFICANT for s in r.segments
               if s.kind is SegmentKind.STABLE)


def test_segments_run_straight_to_straight_one_braking_zone_each():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    data = [s for s in r.segments if s.kind is not SegmentKind.NO_DATA]
    assert len(data) == 2  # two braking zones -> two segments, never 173 fragments
    boundary = data[0].x_end * L
    assert 900 < boundary < 1300  # on the straight between the two braking zones


def test_later_braking_by_b_is_a_significant_loss_for_a_with_brake_evidence():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    seg = _seg_at(r, 550)
    assert seg.kind is SegmentKind.LOSING and seg.significant
    assert seg.accumulated_change_s > seg.uncertainty_s
    br = seg.braking
    assert br.paired
    assert br.onset_offset_m < 0          # A braked earlier (A's onset nearer the start)
    assert abs(br.onset_offset_m + 50) < 25
    assert br.onset_offset_resolvable
    assert seg.primary_signal == "brake"
    assert seg.status is AttributionStatus.SINGLE_CONTROL_INPUT
    assert "speed" in seg.supporting_signals


def test_association_is_temporal_never_causal():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    seg = _seg_at(r, 550)
    first = seg.onset_order[0]
    assert first.signal == "brake_onset"
    assert first.relation_to_midpoint == "BEFORE"
    assert first.association == "TEMPORAL_ASSOCIATION"
    blob = json.dumps(report_to_dict(r)).lower()
    for causal in ("caused", "because", "too late", "too early", "mistake"):
        assert causal not in blob


def test_inherited_gap_is_not_counted_as_new_loss():
    # A loses in corner 1 only; corner 2 identical -> segment 2 inherits the gap
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    seg1, seg2 = _seg_at(r, 550), _seg_at(r, 1340)
    assert seg2.inherited_gap_s == pytest.approx(seg1.delta_end_s, abs=1e-12)
    assert seg2.inherited_gap_s > 0.02
    assert abs(seg2.accumulated_change_s) < seg2.uncertainty_s
    assert seg2.kind is SegmentKind.STABLE


def test_recovery_while_behind_is_labelled_recovering():
    # A loses corner 1 (brakes 50 m early) then gains corner 2 (brakes 50 m late)
    a = two_corner_profile(speed_knots=[(0, 280), (500, 300), (600, 100), (650, 100),
                                        (900, 290), (1300, 300), (1350, 300), (1380, 150),
                                        (1420, 150),
                                        (1650, 290), (2000, 295)],
                           brake=[(500, 600), (1350, 1380)])
    b = two_corner_profile(**LATE_BRAKE_C1)
    r = _report(a, b)
    seg2 = _seg_at(r, 1340)
    assert seg2.inherited_gap_s > 0
    assert seg2.accumulated_change_s < 0 and seg2.significant
    assert seg2.kind is SegmentKind.RECOVERING


def test_multi_signal_has_no_forced_primary():
    late_throttle = {"throttle_knots": [
        (0, 100), (495, 100), (500, 0), (660, 0), (680, 30), (760, 100), (1295, 100),
        (1300, 0), (1400, 0), (1420, 40), (1500, 100), (2000, 100)]}
    r = _report(two_corner_profile(**late_throttle), two_corner_profile(**LATE_BRAKE_C1))
    seg = _seg_at(r, 550)
    assert seg.status is AttributionStatus.MULTI_SIGNAL
    assert seg.primary_signal is None
    assert {"brake", "throttle"} <= set(seg.supporting_signals)


def test_later_throttle_application_is_throttle_evidence():
    late = two_corner_profile(throttle_knots=[
        (0, 100), (495, 100), (500, 0), (660, 0), (680, 30), (760, 100), (1295, 100),
        (1300, 0), (1400, 0), (1420, 40), (1500, 100), (2000, 100)],
        speed_knots=[(0, 280), (500, 300), (600, 100), (680, 100), (920, 290),
                     (1300, 300), (1380, 150), (1420, 150), (1650, 290), (2000, 295)])
    r = _report(late, two_corner_profile())
    seg = _seg_at(r, 550)
    th = seg.throttle
    assert th.application_offset_m > 0          # A applied later
    assert th.application_resolvable
    assert seg.kind is SegmentKind.LOSING
    assert "throttle" in ([seg.primary_signal] + list(seg.supporting_signals))
    assert th.delta_after_application_s is not None


def test_gear_difference_is_categorical_never_subtracted():
    a = two_corner_profile(gear_knots=[(0, 8), (520, 6), (560, 4), (580, 3), (590, 2),
                                       (700, 4), (760, 5), (820, 6), (870, 7), (950, 8),
                                       (1320, 6), (1360, 5), (1450, 6), (1550, 7), (1650, 8)])
    r = _report(a, two_corner_profile())
    g = _seg_at(r, 550).gear
    assert g.available
    assert 0 < g.difference_fraction <= 1
    assert (g.min_a, g.min_b) == (2, 3)
    assert all(isinstance(v, int) for v in (g.min_a, g.min_b))
    assert not hasattr(g, "mean_difference")


def test_drs_difference_and_missing_drs():
    a = two_corner_profile(drs=[(1000, 1290, 12)])
    r = _report(a, two_corner_profile())
    d = _seg_at(r, 1100).drs
    assert d.available and d.difference_fraction > 0
    lap_a, sa = make_lap(two_corner_profile(), 1)
    lap_b, sb = make_lap(two_corner_profile(), 2)
    sa = [s.model_copy(update={"drs": None}) for s in sa]
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    r2 = attribute_comparison(analyze_delta(cmp), lap_a, lap_b)
    assert all(not s.drs.available for s in r2.segments if s.kind is not SegmentKind.NO_DATA)


def test_coverage_gap_is_no_data_never_bridged():
    r = _report(two_corner_profile(), two_corner_profile(), trim_a_m=1700)
    last = r.segments[-1]
    assert last.kind is SegmentKind.NO_DATA
    assert last.accumulated_change_s is None
    assert last.status is AttributionStatus.NO_DATA
    assert r.accounting.no_data_spans


def test_accounting_reconciles_exactly_with_the_delta_curve():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    acc = r.accounting
    total = sum(s.accumulated_change_s for s in r.segments
                if s.accumulated_change_s is not None)
    assert total == pytest.approx(acc.actual_change_s, abs=1e-12)
    parts = (acc.attributed_change_s + acc.unattributed_significant_change_s
             + acc.below_significance_change_s)
    assert parts == pytest.approx(acc.actual_change_s, abs=1e-12)
    assert acc.unaccounted_s == pytest.approx(acc.actual_change_s - acc.attributed_change_s)


def test_braking_split_before_during_after_sums_to_the_segment():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    seg = _seg_at(r, 550)
    br = seg.braking
    assert (br.delta_before_s + br.delta_during_s + br.delta_after_s
            == pytest.approx(seg.accumulated_change_s, abs=1e-12))


def test_phase_accumulation_sums_to_the_segment_for_each_driver():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    seg = _seg_at(r, 550)
    for acc in (seg.phase_accumulation_a, seg.phase_accumulation_b):
        assert sum(acc.values()) == pytest.approx(seg.accumulated_change_s, abs=1e-12)
    assert "APEX" not in seg.phase_accumulation_a


def test_uncertainty_band_grows_in_slow_corners():
    u = AlignmentUncertainty(misalignment_bound_m=4.0, change_bound_m=3.0, anchors=(),
                             source="TEST")
    fast = u.band_s(300 / 3.6, 300 / 3.6)
    slow_end = u.band_s(300 / 3.6, 80 / 3.6)
    assert slow_end > fast
    # exact formula: E*|1/v1-1/v0| + D*max(1/v) + timing resolution
    v0, v1 = 300 / 3.6, 80 / 3.6
    assert slow_end == pytest.approx(4.0 * abs(1 / v1 - 1 / v0) + 3.0 / v1 + 0.001)
    assert fast == pytest.approx(3.0 / v0 + 0.001)


def test_large_alignment_uncertainty_makes_small_losses_not_significant():
    big = AlignmentUncertainty(misalignment_bound_m=400.0, change_bound_m=400.0, anchors=(),
                               source="TEST")
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1), uncertainty=big)
    seg = _seg_at(r, 550)
    assert not seg.significant
    assert seg.kind is SegmentKind.STABLE
    assert seg.status is AttributionStatus.NOT_SIGNIFICANT
    assert r.accounting.attributed_change_s == 0


def test_alignment_is_measured_from_official_sector_lines():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    u = r.uncertainty
    assert u.source == "SECTOR_LINE_ANCHORS"
    assert [a.sector for a in u.anchors] == ["S1", "S2"]
    assert u.misalignment_bound_m == max(abs(a.misalignment_m) for a in u.anchors)
    assert r.alignment_mode is AlignmentMode.NORMALIZED_DISTANCE


def test_without_sector_times_the_default_is_labelled_provisional():
    lap_a, sa = make_lap(two_corner_profile(), 1)
    lap_b, sb = make_lap(two_corner_profile(), 2)
    lap_a = lap_a.model_copy(update={"sector1_s": None, "sector2_s": None})
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    r = attribute_comparison(analyze_delta(cmp), lap_a, lap_b)
    assert r.uncertainty.source == "PROVISIONAL_DEFAULT"
    assert any("PROVISIONAL" in lim for lim in r.limitations)


def test_sectors_use_official_times_and_reconcile():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    assert [s.sector for s in r.sectors] == [1, 2, 3]
    assert sum(s.official_delta_s for s in r.sectors) == pytest.approx(
        r.official_lap_delta_s, abs=0.0015)  # three 1 ms-rounded splits
    s1 = r.sectors[0]
    assert s1.official_delta_s > 0  # A lost corner 1, which lies in sector 1
    assert s1.engine_change_s == pytest.approx(s1.official_delta_s, abs=0.01)


def test_swapping_a_and_b_negates_every_change():
    ab = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    ba = _report(two_corner_profile(**LATE_BRAKE_C1), two_corner_profile())
    assert [(s.start_index, s.end_index) for s in ab.segments] == [
        (s.start_index, s.end_index) for s in ba.segments]
    for s, t in zip(ab.segments, ba.segments):
        if s.accumulated_change_s is not None:
            assert t.accumulated_change_s == pytest.approx(-s.accumulated_change_s, abs=1e-12)


def test_output_is_byte_identical_on_rerun():
    def run():
        r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
        return json.dumps(report_to_dict(r), sort_keys=True)
    assert run() == run()


def test_context_facts_carry_no_raw_telemetry():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    pack = attribution_facts(r)
    assert pack["pack"] == "lap_attribution_v1"
    blob = json.dumps(pack)
    assert "samples" not in blob and "points" not in blob
    ids = [f["id"] for f in pack["facts"]]
    assert len(ids) == len(set(ids))
    seg_fact = next(f for f in pack["facts"] if f["id"].startswith("seg"))
    assert {"accumulated_change_s", "inherited_gap_s", "uncertainty_s", "alignment_mode",
            "significant", "phase"} <= set(seg_fact["values"])


def test_provenance_traces_segment_to_samples_and_lap():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    seg = _seg_at(r, 550)
    p = seg.provenance
    assert p.grid_indices == (seg.start_index, seg.end_index)
    lo, hi = p.sample_indices_a
    assert 0 <= lo <= hi
    assert p.session_id == r.session_id and p.lap_a == r.lap_a
    assert p.calc_version.startswith("attribution-")


def test_official_only_sector_fact_is_historical_class_b():
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    facts = {f["id"]: f for f in attribution_facts(r)["facts"]}
    assert r.sectors[2].engine_change_s is None
    assert facts["attr_sector3"]["class"] == "B"   # official timing only: observed, historical
    assert facts["attr_sector1"]["class"] == "C"   # includes an engine-derived value


@pytest.mark.parametrize("field,code", [
    ("throttle_pct", "THROTTLE_CHANNEL_MISSING"), ("brake_pct", "BRAKE_CHANNEL_MISSING"),
    ("gear", "GEAR_CHANNEL_MISSING"), ("drs", "DRS_CHANNEL_MISSING")])
def test_missing_channels_are_structured_limitations(field, code):
    lap_a, sa = make_lap(two_corner_profile(), 1)
    lap_b, sb = make_lap(two_corner_profile(), 2)
    sa = [s.model_copy(update={field: None}) for s in sa]
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    r = attribute_comparison(analyze_delta(cmp), lap_a, lap_b)
    assert code in {x.code for x in r.limitation_items}
    channel = {"throttle_pct": "throttle", "brake_pct": "brake"}.get(field, field)
    assert r.channels["a"][channel] is False and r.channels["b"][channel] is True


def test_limitation_items_are_the_authoritative_structured_form():
    from app.analysis.attribution import LimitationCode
    r = _report(two_corner_profile(), two_corner_profile(**LATE_BRAKE_C1))
    assert [x.message for x in r.limitation_items] == r.limitations
    assert all(x.code in LimitationCode.__members__ for x in r.limitation_items)
    codes = {x.code for x in r.limitation_items}
    assert {"ALIGNMENT_NORMALIZED_DISTANCE", "NO_TRACK_GEOMETRY",
            "ASSOCIATION_NOT_CAUSATION"} <= codes
