"""Phase 10.4 invariants, checked across a family of SYNTHETIC scenarios.

Each property must hold for every scenario (different braking points,
throttle, gears, DRS, sampling rates and sampling phases per driver) - not
for one hand-picked case.
"""

from __future__ import annotations

import json
import math

import pytest
from synthetic_lap import make_lap, two_corner_profile

from app.analysis.attribution import AttributionStatus, attribute_comparison, report_to_dict
from app.analysis.delta_analysis import SegmentKind, analyze_delta
from app.analysis.lap_comparison import compare_driver_laps

L = 2000.0
VARIANTS = {
    "late_brake": {
        "speed_knots": [(0, 280), (500, 300), (550, 300), (600, 100), (650, 100), (900, 290),
                     (1300, 300), (1380, 150), (1420, 150), (1650, 290), (2000, 295)],
        "brake": [(550, 600), (1300, 1380)]},
    "late_throttle": {"throttle_knots": [
        (0, 100), (495, 100), (500, 0), (660, 0), (680, 30), (760, 100), (1295, 100),
        (1300, 0), (1400, 0), (1420, 40), (1500, 100), (2000, 100)]},
    "lower_min_speed": {
        "speed_knots": [(0, 280), (500, 300), (600, 90), (650, 90), (900, 285),
                     (1300, 300), (1380, 150), (1420, 150), (1650, 290), (2000, 295)]},
    "second_gear": {"gear_knots": [(0, 8), (520, 6), (560, 4), (580, 3), (590, 2), (700, 4),
                                    (760, 5), (820, 6), (870, 7), (950, 8), (1320, 6),
                                    (1360, 5), (1450, 6), (1550, 7), (1650, 8)]},
    "drs": {"drs": [(1000, 1290, 12)]},
}
SAMPLING = [(3.7, 0.0, 0.0), (3.7, 0.0, 0.13), (4.0, 0.05, 0.2)]


def _run(prof_a, prof_b, hz=3.7, phase_a=0.0, phase_b=0.0):
    lap_a, sa = make_lap(prof_a, 1, hz=hz, phase_s=phase_a)
    lap_b, sb = make_lap(prof_b, 2, hz=hz, phase_s=phase_b)
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    an = analyze_delta(cmp)
    return an, attribute_comparison(an, lap_a, lap_b)


CASES = [(name, s) for name in VARIANTS for s in SAMPLING]


@pytest.mark.parametrize("hz,pa,pb", SAMPLING)
def test_identical_telemetry_has_no_gain_loss_and_nothing_attributed(hz, pa, pb):
    _an, r = _run(two_corner_profile(), two_corner_profile(), hz, pa, pa)
    assert all(s.kind in (SegmentKind.STABLE, SegmentKind.NO_DATA) for s in r.segments)
    assert r.accounting.attributed_change_s == 0
    assert r.accounting.unattributed_significant_change_s == 0


@pytest.mark.parametrize("hz,pa,pb", SAMPLING)
def test_same_driving_different_sampling_phase_is_never_significant(hz, pa, pb):
    # Same car, same lap, samples taken at different instants: any change is
    # sampling/quantization noise and must stay inside the band.
    _an, r = _run(two_corner_profile(), two_corner_profile(), hz, pa, pb)
    assert all(not s.significant for s in r.segments)


def test_constant_gap_from_an_earlier_loss_is_never_new_loss():
    # A is slower only on the opening straight, identical afterwards.
    slow_start = {"speed_knots": [(0, 260), (400, 280), (500, 300), (600, 100), (650, 100),
                                   (900, 290), (1300, 300), (1380, 150), (1420, 150),
                                   (1650, 290), (2000, 295)]}
    _an, r = _run(two_corner_profile(**slow_start), two_corner_profile())
    later = [s for s in r.segments if s.kind is not SegmentKind.NO_DATA][1:]
    assert later and all(s.inherited_gap_s > 0 for s in later)
    assert all(not s.significant for s in later)


@pytest.mark.parametrize("name,sampling", CASES)
def test_region_changes_reconcile_with_the_curve(name, sampling):
    an, r = _run(two_corner_profile(), two_corner_profile(**VARIANTS[name]), *sampling)
    for s in r.segments:
        if s.accumulated_change_s is None:
            continue
        # exactly the curve's change - no event claims more than the delta moved
        assert s.accumulated_change_s == (an.samples[s.end_index].delta_t_s
                                          - an.samples[s.start_index].delta_t_s)
    acc = r.accounting
    assert sum(s.accumulated_change_s for s in r.segments
               if s.accumulated_change_s is not None) == pytest.approx(acc.actual_change_s,
                                                                       abs=1e-12)
    assert (acc.attributed_change_s + acc.unattributed_significant_change_s
            + acc.below_significance_change_s) == pytest.approx(acc.actual_change_s, abs=1e-12)


@pytest.mark.parametrize("name,sampling", CASES)
def test_swapping_a_and_b_negates(name, sampling):
    hz, pa, pb = sampling
    _a1, ab = _run(two_corner_profile(), two_corner_profile(**VARIANTS[name]), hz, pa, pb)
    _a2, ba = _run(two_corner_profile(**VARIANTS[name]), two_corner_profile(), hz, pb, pa)
    assert [(s.start_index, s.end_index) for s in ab.segments] == [
        (s.start_index, s.end_index) for s in ba.segments]
    for s, t in zip(ab.segments, ba.segments):
        if s.accumulated_change_s is not None:
            assert t.accumulated_change_s == pytest.approx(-s.accumulated_change_s, abs=1e-12)
            assert s.significant == t.significant


@pytest.mark.parametrize("name,sampling", CASES)
def test_gear_and_drs_values_are_never_fractional(name, sampling):
    _an, r = _run(two_corner_profile(), two_corner_profile(**VARIANTS[name]), *sampling)
    for s in r.segments:
        for ev in (s.gear, s.drs):
            for v in (ev.min_a, ev.min_b, *ev.values_a, *ev.values_b):
                assert v is None or (isinstance(v, int) and not isinstance(v, bool))
            if ev.difference_fraction is not None:
                assert 0 <= ev.difference_fraction <= 1


@pytest.mark.parametrize("field", ["throttle_pct", "gear", "brake_pct"])
def test_missing_channel_never_becomes_evidence(field):
    lap_a, sa = make_lap(two_corner_profile(), 1)
    lap_b, sb = make_lap(two_corner_profile(**VARIANTS["late_brake"]), 2)
    sa = [s.model_copy(update={field: None}) for s in sa]
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    r = attribute_comparison(analyze_delta(cmp), lap_a, lap_b)
    for s in r.segments:
        signals = {o.signal for o in s.onset_order}
        if field == "throttle_pct":
            assert not signals & {"throttle_lift", "throttle_application", "full_throttle"}
        if field == "gear":
            assert not s.gear.available and "gear" not in signals
        if field == "brake_pct":
            # a MISSING channel is not "did not brake": no unpaired-braking claim either
            assert s.braking is None
            assert not any(x.startswith("brake") for x in signals)


@pytest.mark.parametrize("name,sampling", CASES)
def test_output_is_deterministic(name, sampling):
    def dump():
        _an, r = _run(two_corner_profile(), two_corner_profile(**VARIANTS[name]), *sampling)
        return json.dumps(report_to_dict(r), sort_keys=True)
    one = dump()
    assert one == dump()
    assert "NaN" not in one and "Infinity" not in one


@pytest.mark.parametrize("name,sampling", CASES)
def test_status_never_names_a_primary_without_a_significant_change(name, sampling):
    _an, r = _run(two_corner_profile(), two_corner_profile(**VARIANTS[name]), *sampling)
    for s in r.segments:
        if not s.significant:
            assert s.primary_signal is None and s.supporting_signals == ()
            assert s.status in (AttributionStatus.NOT_SIGNIFICANT, AttributionStatus.NO_DATA)
        if s.uncertainty_s is not None:
            assert math.isfinite(s.uncertainty_s) and s.uncertainty_s >= 0.001
