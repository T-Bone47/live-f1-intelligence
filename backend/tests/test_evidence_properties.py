"""evidence_v1 invariants across the Phase 10.4 SYNTHETIC scenario family.

The same 5 perturbations x 3 sampling setups used for 10.4's properties
(tests/test_attribution_properties.py), now through the evidence layer.
"""

from __future__ import annotations

import json

import pytest
from synthetic_lap import SID, make_lap, two_corner_profile
from test_attribution_properties import SAMPLING, VARIANTS

from app.analysis.delta_analysis import SIGN_CONVENTION
from app.evidence import SourceInfo, build_lap_comparison_evidence, to_canonical_json

CASES = [(name, s) for name in VARIANTS for s in SAMPLING]
SRC = SourceInfo(session_id=SID, provider="openf1")


def _ev(prof_a, prof_b, hz, pa, pb):
    lap_a, sa = make_lap(prof_a, 1, hz=hz, phase_s=pa)
    lap_b, sb = make_lap(prof_b, 2, hz=hz, phase_s=pb)
    return build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=2000.0,
                                         lap_length_source="synthetic", source=SRC)


def _numeric_lists(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _numeric_lists(v)
    elif isinstance(obj, list):
        if obj and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in obj):
            yield obj
        for v in obj:
            yield from _numeric_lists(v)


@pytest.mark.parametrize("name,sampling", CASES)
def test_evidence_invariants(name, sampling):
    ev = _ev(two_corner_profile(), two_corner_profile(**VARIANTS[name]), *sampling)
    raw = to_canonical_json(ev)
    data = json.loads(raw)
    assert ev.comparison.sign_convention == SIGN_CONVENTION
    assert ev.calculation.attribution_version and ev.calculation.lap_distance_version
    acc = ev.attribution.accounting
    assert (acc.attributed_change_s + acc.unattributed_significant_change_s
            + acc.below_significance_change_s) == pytest.approx(acc.actual_change_s, abs=1e-12)
    idx = [s.grid_start_index for s in ev.attribution.segments]
    assert idx == sorted(idx)
    assert max(len(v) for v in _numeric_lists(data)) <= 16  # no raw streams
    drivers = {(1, 1), (2, 1)}
    for s in ev.attribution.segments:
        assert {(r.driver_number, r.lap_number) for r in s.telemetry_references} <= drivers
    assert {lp.session_id for lp in ev.provenance.laps} == {SID}
    assert raw == to_canonical_json(_ev(two_corner_profile(),
                                        two_corner_profile(**VARIANTS[name]), *sampling))


@pytest.mark.parametrize("name,sampling", CASES)
def test_swapping_a_and_b_changes_identity_and_negates_every_change(name, sampling):
    hz, pa, pb = sampling
    ab = _ev(two_corner_profile(), two_corner_profile(**VARIANTS[name]), hz, pa, pb)
    ba = _ev(two_corner_profile(**VARIANTS[name]), two_corner_profile(), hz, pb, pa)
    assert ab.evidence_id != ba.evidence_id
    for s, t in zip(ab.attribution.segments, ba.attribution.segments, strict=True):
        assert (s.grid_start_index, s.grid_end_index) == (t.grid_start_index, t.grid_end_index)
        if s.accumulated_change_s is not None:
            assert t.accumulated_change_s == pytest.approx(-s.accumulated_change_s, abs=1e-12)
            assert s.significant == t.significant
