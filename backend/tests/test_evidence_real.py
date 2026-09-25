"""evidence_v1 on the REAL Singapore pair (session 9161, #55 lap 19 vs #63 lap 16).

Path: raw OpenF1 rows -> identity guard -> mapper -> 10.1B -> 10.1C -> 10.2 ->
10.4 -> 10.5. Every exposed value is compared with a DIRECT 10.4 run on the
same rows - nothing is hard-coded - and the golden bytes + schema are locked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.analysis.attribution import attribute_comparison
from app.analysis.delta_analysis import SegmentKind, analyze_delta
from app.analysis.lap_comparison import compare_driver_laps
from app.evidence import parse_evidence, to_canonical_json
from app.evidence.schema import json_schema
from app.providers.openf1.mapping import to_car_sample, to_lap

ROOT = Path(__file__).parent.parent.parent
FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
GOLDEN = ROOT / "docs" / "evidence" / "evidence_v1_singapore.json"
SCHEMA = ROOT / "docs" / "evidence" / "evidence_v1.schema.json"
sys.path.insert(0, str(ROOT / "scripts"))

pytestmark = pytest.mark.skipif(not (FIXTURE / "meta.json").exists(),
                                reason="no real two-driver fixture")


@pytest.fixture(scope="module")
def real():
    from evidence_report import build_real_evidence
    meta = json.loads((FIXTURE / "meta.json").read_text())
    sid = f"openf1:{meta['session_key']}"
    laps, samples = {}, {}
    for d in (meta["driver_a"], meta["driver_b"]):
        laps[d], _ = to_lap(json.loads((FIXTURE / f"driver_{d}_lap.json").read_text()), sid)
        rows = json.loads((FIXTURE / f"driver_{d}_car_data.json").read_text())
        samples[d] = sorted((to_car_sample(r, sid) for r in rows), key=lambda s: s.ts)
    a, b = meta["driver_a"], meta["driver_b"]
    cmp = compare_driver_laps(laps[a], samples[a], None, laps[b], samples[b], None,
                              lap_length_m=meta["lap_length_m"])
    direct = attribute_comparison(analyze_delta(cmp), laps[a], laps[b])
    return build_real_evidence(), direct, meta


def test_every_segment_value_equals_direct_10_4(real):
    ev, rep, _meta = real
    assert len(ev.attribution.segments) == len(rep.segments)
    for e, s in zip(ev.attribution.segments, rep.segments, strict=True):
        assert (e.label, e.grid_start_index, e.grid_end_index) == (
            s.region_id, s.start_index, s.end_index)
        assert e.accumulated_change_s == s.accumulated_change_s
        assert e.inherited_gap_s == s.inherited_gap_s
        assert e.uncertainty_s == s.uncertainty_s
        assert e.significant == s.significant
        assert e.attribution_status.value == s.status.value
        assert e.direction.value == s.kind.value
        assert [o.signal for o in e.onset_order] == [o.signal for o in s.onset_order]
        if s.braking is None:
            assert e.braking is None
        else:
            assert e.braking.onset_offset_m == s.braking.onset_offset_m
            assert e.braking.onset_offset_resolvable == s.braking.onset_offset_resolvable
            assert e.braking.release_offset_m == s.braking.release_offset_m
        if s.throttle is not None:
            assert e.throttle.application_offset_m == s.throttle.application_offset_m
            assert e.throttle.full_offset_m == s.throttle.full_offset_m
        assert (e.gear.min_a, e.gear.min_b) == (s.gear.min_a, s.gear.min_b)
        if s.speed is not None:
            assert e.speed.min_speed_difference_kph == s.speed.min_speed_difference_kph


def test_comparison_sectors_and_accounting_equal_direct_10_4(real):
    ev, rep, meta = real
    c = ev.comparison
    assert c.lap_delta_s == rep.official_lap_delta_s
    assert c.engine_delta_last_covered_s == rep.engine_delta_last_covered_s
    assert c.alignment.misalignment_bound_m == rep.uncertainty.misalignment_bound_m
    assert c.alignment.uncertainty_source == rep.uncertainty.source
    assert c.lap_length.m == meta["lap_length_m"]
    assert c.lap_length.source == meta["lap_length_source"]
    for e, s in zip(ev.attribution.sectors, rep.sectors, strict=True):
        assert (e.official_delta_s, e.engine_change_s) == (s.official_delta_s, s.engine_change_s)
    acc, racc = ev.attribution.accounting, rep.accounting
    assert (acc.actual_change_s, acc.attributed_change_s, acc.below_significance_change_s) == (
        racc.actual_change_s, racc.attributed_change_s, racc.below_significance_change_s)
    assert [x.code.value for x in ev.limitations] == [x.code for x in rep.limitation_items]


def test_real_evidence_keeps_the_verified_10_4_properties(real):
    ev, rep, _meta = real
    data = [s for s in ev.attribution.segments if s.direction is not SegmentKind.NO_DATA]
    assert len(data) == len([s for s in rep.segments if s.kind is not SegmentKind.NO_DATA])
    # exposure never manufactures significance
    assert [s.significant for s in ev.attribution.segments] == [
        s.significant for s in rep.segments]
    # the resolvable control-input differences stay available, as associations
    assert any(s.braking and s.braking.onset_offset_resolvable for s in data)
    assert any(s.gear.min_a != s.gear.min_b for s in data)
    assert any(s.throttle and (s.throttle.application_resolvable or s.throttle.full_resolvable)
               for s in data)
    assert all(o.association == "TEMPORAL_ASSOCIATION" for s in data for o in s.onset_order)
    assert ev.source.event is None  # the fixture records no meeting name
    assert ev.attribution.sectors[2].coverage == "NOT_COVERED"


def test_golden_fixture_is_byte_identical_and_round_trips(real):
    ev, _rep, _meta = real
    if not GOLDEN.exists():
        pytest.skip("golden not generated yet (scripts/evidence_report.py)")
    golden = GOLDEN.read_bytes().rstrip(b"\n")
    assert to_canonical_json(ev) == golden
    parsed = parse_evidence(golden)
    assert to_canonical_json(parsed) == golden  # deserialize -> validate -> serialize
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == json_schema()


def test_real_evidence_is_deterministic(real):
    from evidence_report import build_real_evidence
    ev, _rep, _meta = real
    assert to_canonical_json(build_real_evidence()) == to_canonical_json(ev)
