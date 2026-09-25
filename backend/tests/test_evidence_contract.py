"""evidence_v1 contract: serialization, validation, propagation, negative cases.

Synthetic laps (tests/synthetic_lap.py) pin contract MECHANICS; real-data
agreement lives in tests/test_evidence_real.py. Every negative case must fail
explicitly - EvidenceInputError (the request cannot give honest evidence) or
EvidenceContractError (the evidence would violate evidence_v1) - never by
returning plausible-looking evidence.
"""

from __future__ import annotations

import copy
import dataclasses
import json

import pytest
from synthetic_lap import SID, make_lap, two_corner_profile

from app.analysis.attribution import CALC_VERSION, attribute_comparison
from app.analysis.delta_analysis import SIGN_CONVENTION, analyze_delta
from app.analysis.lap_comparison import compare_driver_laps
from app.evidence import (
    CONTRACT_VERSION,
    EvidenceContractError,
    EvidenceInputError,
    SourceInfo,
    build_lap_comparison_evidence,
    parse_evidence,
    to_canonical_json,
)
from app.evidence.lap_comparison import evidence_from_report, input_digest

L = 2000.0
LATE = {"speed_knots": [(0, 280), (500, 300), (550, 300), (600, 100), (650, 100), (900, 290),
                         (1300, 300), (1380, 150), (1420, 150), (1650, 290), (2000, 295)],
            "brake": [(550, 600), (1300, 1380)]}
SRC = SourceInfo(session_id=SID, provider="openf1", session_type="Qualifying", season=2026,
                 event=None, circuit=None)
CITE = "synthetic test profile (2,000 m by construction)"


def _laps(prof_a=None, prof_b=None, update_a=None, trim_a=None):
    lap_a, sa = make_lap(prof_a or two_corner_profile(), 1)
    lap_b, sb = make_lap(prof_b or two_corner_profile(**LATE), 2)
    if update_a:
        sa = [s.model_copy(update=update_a) for s in sa]
    if trim_a:
        sa = sa[:int(len(sa) * trim_a)]
    return lap_a, sa, lap_b, sb


def _ev(**kw):
    lap_a, sa, lap_b, sb = _laps(**kw)
    return build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=L,
                                         lap_length_source=CITE, source=SRC)


def _dict(ev):
    return json.loads(to_canonical_json(ev))


# ------------------------------------------------------------ serialization


def test_canonical_json_round_trip_is_byte_stable():
    ev = _ev()
    raw = to_canonical_json(ev)
    assert raw == to_canonical_json(parse_evidence(raw))
    assert raw == to_canonical_json(_ev())  # independent rebuild: same bytes
    assert raw.startswith(b'{"attribution":{')  # sorted keys, no whitespace
    assert b"NaN" not in raw and b"Infinity" not in raw


def test_versions_and_identity_are_explicit():
    ev = _ev()
    assert ev.contract_version == CONTRACT_VERSION == "evidence_v1"
    assert ev.calculation.attribution_version == CALC_VERSION
    assert ev.calculation.lap_distance_version.startswith("lap-distance-")
    assert ev.comparison.sign_convention == SIGN_CONVENTION
    assert ev.source.session_id == SID
    assert (ev.comparison.driver_a.driver_number, ev.comparison.driver_b.driver_number) == (1, 2)


def test_ids_are_stable_content_addressed_and_not_positional():
    ev = _ev()
    assert ev.evidence_id.startswith("ev1_")
    for s in ev.attribution.segments:
        assert s.segment_id == f"{ev.evidence_id}:g{s.grid_start_index}-{s.grid_end_index}"
    assert _ev(prof_b=two_corner_profile()).evidence_id != ev.evidence_id  # changed rows


def test_null_means_unavailable_never_a_guess():
    ev = _ev()
    assert ev.source.event is None and ev.source.circuit is None
    tail = ev.attribution.segments[-1]
    assert tail.direction.value == "NO_DATA"
    assert tail.accumulated_change_s is None and tail.provenance_class == "F"


def test_values_are_10_4_values_unrounded():
    lap_a, sa, lap_b, sb = _laps()
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    rep = attribute_comparison(analyze_delta(cmp), lap_a, lap_b)
    ev = evidence_from_report(rep, cmp, lap_a, lap_b, source=SRC, lap_length_source=CITE,
                              digest=input_digest(lap_a, sa, lap_b, sb))
    for seg, e in zip(rep.segments, ev.attribution.segments, strict=True):
        assert e.accumulated_change_s == seg.accumulated_change_s   # exact, not rounded
        assert e.uncertainty_s == seg.uncertainty_s
        assert e.inherited_gap_s == seg.inherited_gap_s
        assert e.significant == seg.significant
        assert e.attribution_status.value == seg.status.value
        assert e.direction.value == seg.kind.value
        assert [o.signal for o in e.onset_order] == [o.signal for o in seg.onset_order]
    acc = ev.attribution.accounting
    assert acc.actual_change_s == rep.accounting.actual_change_s
    assert acc.attributed_change_s == rep.accounting.attributed_change_s


def test_significance_association_and_recovery_propagate():
    ev = _ev()
    seg = next(s for s in ev.attribution.segments if s.significant)
    assert seg.direction.value == "LOSING" and seg.primary_signal == "brake"
    assert seg.association == "TEMPORAL_ASSOCIATION"
    assert all(o.association == "TEMPORAL_ASSOCIATION" for o in seg.onset_order)
    blob = to_canonical_json(ev).decode().lower()
    assert '"causal' not in blob and '"cause' not in blob
    rec = _ev(prof_a=two_corner_profile(
        speed_knots=[(0, 280), (500, 300), (600, 100), (650, 100), (900, 290), (1300, 300),
                     (1350, 300), (1380, 150), (1420, 150), (1650, 290), (2000, 295)],
        brake=[(500, 600), (1350, 1380)]))
    assert any(s.direction.value == "RECOVERING" and s.inherited_gap_s > 0
               for s in rec.attribution.segments)


def test_limitations_are_structured_codes():
    ev = _ev()
    codes = [x.code.value for x in ev.limitations]
    assert "ALIGNMENT_NORMALIZED_DISTANCE" in codes and "NO_TRACK_GEOMETRY" in codes
    assert "ASSOCIATION_NOT_CAUSATION" in codes
    assert all(x.message for x in ev.limitations)


def _numeric_lists(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _numeric_lists(v)
    elif isinstance(obj, list):
        if obj and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in obj):
            yield obj
        for v in obj:
            yield from _numeric_lists(v)


def test_no_raw_telemetry_and_no_geometry_claims():
    data = _dict(_ev())
    raw = json.dumps(data)
    # a raw stream is hundreds of numbers per lap; the longest legitimate numeric
    # list is a driver's distinct gears (<= 9)
    assert max(len(v) for v in _numeric_lists(data)) <= 16
    for key in ('"speed_kph"', '"throttle_pct"', '"brake_pct"', '"rpm"', '"gps"',
                '"apex"', '"corner_name"', '"samples"'):
        assert key not in raw, key


# ---------------------------------------------------------- negative cases


def test_n1_missing_lap_duration():
    lap_a, sa, lap_b, sb = _laps()
    lap_a = lap_a.model_copy(update={"duration_s": None})
    with pytest.raises(EvidenceInputError, match="no duration"):
        build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=L,
                                      lap_length_source=CITE, source=SRC)


@pytest.mark.parametrize("length", [0.0, -1.0, float("nan"), float("inf")])
def test_n2_missing_or_impossible_lap_length(length):
    lap_a, sa, lap_b, sb = _laps()
    with pytest.raises(EvidenceInputError, match="lap_length_m"):
        build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=length,
                                      lap_length_source=CITE, source=SRC)


@pytest.mark.parametrize("cite", ["", "   ", "a\x00b", "x" * 301])
def test_n3_invalid_lap_length_source(cite):
    lap_a, sa, lap_b, sb = _laps()
    with pytest.raises(EvidenceInputError, match="lap_length_source"):
        build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=L,
                                      lap_length_source=cite, source=SRC)


def test_n4_cross_session_is_refused():
    lap_a, sa, lap_b, sb = _laps()
    lap_b = lap_b.model_copy(update={"session_id": "synthetic:other"})
    sb = [s.model_copy(update={"session_id": "synthetic:other"}) for s in sb]
    with pytest.raises(EvidenceInputError, match="cross-session"):
        build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=L,
                                      lap_length_source=CITE, source=SRC)


@pytest.mark.parametrize("driver", [0, 100, -5])
def test_n5_invalid_driver(driver):
    lap_a, sa, lap_b, sb = _laps()
    lap_a = lap_a.model_copy(update={"driver_number": driver})
    with pytest.raises(EvidenceInputError, match="driver_a"):
        build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=L,
                                      lap_length_source=CITE, source=SRC)


def test_n6_invalid_or_identical_lap():
    lap_a, sa, lap_b, sb = _laps()
    with pytest.raises(EvidenceInputError, match="lap_a"):
        build_lap_comparison_evidence(lap_a.model_copy(update={"lap_number": 0}), sa, lap_b, sb,
                                      lap_length_m=L, lap_length_source=CITE, source=SRC)
    same = lap_b.model_copy(update={"driver_number": 1, "lap_number": lap_a.lap_number})
    with pytest.raises(EvidenceInputError, match="same lap"):
        build_lap_comparison_evidence(lap_a, sa, same, sa, lap_length_m=L,
                                      lap_length_source=CITE, source=SRC)


def test_n7_missing_telemetry():
    lap_a, _sa, lap_b, sb = _laps()
    with pytest.raises(EvidenceInputError, match="no telemetry"):
        build_lap_comparison_evidence(lap_a, [], lap_b, sb, lap_length_m=L,
                                      lap_length_source=CITE, source=SRC)


def test_n8_n12_partial_and_incomplete_final_telemetry_are_explicit():
    ev = _ev(trim_a=0.8)
    assert "TELEMETRY_COVERAGE_INCOMPLETE" in {x.code.value for x in ev.limitations}
    assert ev.attribution.segments[-1].direction.value == "NO_DATA"
    assert ev.comparison.driver_a.telemetry.complete is False
    s3 = ev.attribution.sectors[2]
    assert s3.coverage == "NOT_COVERED" and s3.engine_change_s is None
    assert s3.engine_provenance_class == "F"


def test_n9_missing_brake_channel():
    ev = _ev(update_a={"brake_pct": None})
    assert "BRAKE_CHANNEL_MISSING" in {x.code.value for x in ev.limitations}
    assert all(s.braking is None for s in ev.attribution.segments)
    assert ev.comparison.driver_a.telemetry.channels.brake is False


def test_n10_missing_throttle_channel():
    ev = _ev(update_a={"throttle_pct": None})
    assert "THROTTLE_CHANNEL_MISSING" in {x.code.value for x in ev.limitations}
    for s in ev.attribution.segments:
        assert not any(o.family == "throttle" for o in s.onset_order)


def test_n11_missing_sector_timing():
    lap_a, sa, lap_b, sb = _laps()
    lap_a = lap_a.model_copy(update={"sector1_s": None, "sector2_s": None, "sector3_s": None})
    ev = build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=L,
                                       lap_length_source=CITE, source=SRC)
    for sec in ev.attribution.sectors:
        assert sec.official_delta_s is None and sec.official_provenance_class == "F"
    assert ev.comparison.alignment.uncertainty_source == "PROVISIONAL_DEFAULT"
    assert "UNCERTAINTY_DEFAULT_PROVISIONAL" in {x.code.value for x in ev.limitations}


def test_n13_invalid_attribution_object_is_withheld():
    lap_a, sa, lap_b, sb = _laps()
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    rep = attribute_comparison(analyze_delta(cmp), lap_a, lap_b)
    dig = input_digest(lap_a, sa, lap_b, sb)
    bad = copy.copy(rep)
    seg = next(s for s in rep.segments if s.significant)
    bad.segments = [dataclasses.replace(s, significant=False) if s is seg else s
                    for s in rep.segments]
    with pytest.raises(EvidenceContractError):
        evidence_from_report(bad, cmp, lap_a, lap_b, source=SRC, lap_length_source=CITE,
                             digest=dig)
    future = copy.copy(rep)
    future.calc_version = "attribution-9.9.9"
    with pytest.raises(EvidenceContractError, match="not a version this builder maps"):
        evidence_from_report(future, cmp, lap_a, lap_b, source=SRC, lap_length_source=CITE,
                             digest=dig)


def test_n14_corrupted_provenance_and_identity():
    lap_a, sa, lap_b, sb = _laps()
    cmp = compare_driver_laps(lap_a, sa, None, lap_b, sb, None, lap_length_m=L)
    rep = attribute_comparison(analyze_delta(cmp), lap_a, lap_b)
    with pytest.raises(EvidenceContractError, match="identity"):
        evidence_from_report(rep, cmp, lap_a.model_copy(update={"lap_number": 7}), lap_b,
                             source=SRC, lap_length_source=CITE,
                             digest=input_digest(lap_a, sa, lap_b, sb))
    # samples of another driver smuggled into A's lap (the cache-contamination bug class)
    with pytest.raises(EvidenceInputError, match="identity guard"):
        build_lap_comparison_evidence(lap_a, sb, lap_b, sb, lap_length_m=L,
                                      lap_length_source=CITE, source=SRC)


def test_n15_unsupported_contract_version():
    lap_a, sa, lap_b, sb = _laps()
    with pytest.raises(EvidenceInputError, match="unsupported contract_version"):
        build_lap_comparison_evidence(lap_a, sa, lap_b, sb, lap_length_m=L,
                                      lap_length_source=CITE, source=SRC,
                                      contract_version="evidence_v2")
    data = _dict(_ev())
    data["contract_version"] = "evidence_v2"
    with pytest.raises(EvidenceContractError, match="unsupported contract_version"):
        parse_evidence(data)


# ------------------------------------------- tampering (mutation of payload)


def _sig(d):
    return next(s for s in d["attribution"]["segments"] if s["significant"])


def _quiet(d):
    return next(s for s in d["attribution"]["segments"]
                if not s["significant"] and s["accumulated_change_s"] is not None)


TAMPERS = {
    "driver identity": lambda d: d["comparison"]["driver_a"].update(driver_number=44),
    "lap identity": lambda d: d["comparison"]["driver_b"].update(lap_number=9),
    "session identity": lambda d: d["source"].update(session_id="openf1:other"),
    "sign convention": lambda d: d["comparison"].update(sign_convention="A minus B"),
    "significance flipped": lambda d: _sig(d).update(significant=False),
    "uncertainty shrunk": lambda d: _quiet(d).update(uncertainty_s=0.0),
    "accounting": lambda d: d["attribution"]["accounting"].update(attributed_change_s=1.0),
    # breaks ONLY attributed + unattributed + below == actual (unaccounted stays consistent)
    "accounting parts": lambda d: d["attribution"]["accounting"].update(
        below_significance_change_s=d["attribution"]["accounting"]
        ["below_significance_change_s"] + 0.05),
    "segment id": lambda d: _sig(d).update(segment_id=_sig(d)["segment_id"] + "x"),
    "input digest": lambda d: d["provenance"].update(input_digest="sha256:" + "0" * 64),
    "causal association": lambda d: _sig(d).update(association="CAUSAL"),
    "extra cause field": lambda d: _sig(d).update(cause="late braking"),
    "number as string": lambda d: _sig(d).update(accumulated_change_s="0.1"),
    "unknown limitation": lambda d: d["limitations"].append({"code": "X", "message": "y"}),
    "reference to another driver": lambda d: _sig(d)["telemetry_references"][0].update(
        driver_number=44),
    "calculation version dropped": lambda d: d["calculation"].pop("attribution_version"),
    "contract version inside": lambda d: d["calculation"].update(contract_version="v0"),
    "segment order": lambda d: d["attribution"]["segments"].reverse(),
    "sector coverage lie": lambda d: d["attribution"]["sectors"][2].update(coverage="COVERED"),
}


@pytest.mark.parametrize("name", sorted(TAMPERS))
def test_tampered_evidence_is_rejected(name):
    data = _dict(_ev())
    TAMPERS[name](data)
    with pytest.raises(EvidenceContractError):
        parse_evidence(data)


def test_untampered_evidence_is_accepted():
    parse_evidence(_dict(_ev()))
