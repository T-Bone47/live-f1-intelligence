"""Phase 10.5 builder: Phase 10.4 AttributionReport -> evidence_v1.

A RESTRUCTURE, never a recomputation: every analytical value is read from
the 10.4 report (or the 10.1B/10.1C objects it was computed from) and passed
through unrounded. What this module adds is only what a consumer needs and
10.4 does not carry: stable identifiers, source metadata, request/identity
validation, provenance references and canonical serialization.

Fails closed: an input that cannot yield honest evidence raises
EvidenceInputError (HTTP 422); evidence that does not satisfy the contract
raises EvidenceContractError (HTTP 500) and is never returned as evidence_v1.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import ValidationError

from app.analysis.attribution import AttributionReport, attribute_comparison
from app.analysis.delta_analysis import SegmentKind, analyze_delta
from app.analysis.lap_comparison import DriverLapComparison, compare_driver_laps
from app.analysis.lap_distance import CALC_VERSION as LAP_DISTANCE_VERSION
from app.analysis.lap_distance import LapDistanceTrace
from app.core.models import Lap, TelemetryCarSample
from app.evidence.schema import (
    ASSOCIATION,
    CONTRACT_VERSION,
    SUPPORTED_CONTRACTS,
    LapComparisonEvidenceV1,
    evidence_id_for,
    sector_id_for,
    segment_id_for,
)

BUILDER_VERSION = "evidence-builder-1.0.0"
# The 10.4 versions whose report shape this builder maps. A new 10.4 version
# fails closed here until the mapping is reviewed - never silently re-labelled.
SUPPORTED_ATTRIBUTION_VERSIONS = ("attribution-1.1.0",)
TELEMETRY_ROUTE = "/api/v1/sessions/{session_id}/telemetry/{driver_number}"
MAX_SOURCE_CHARS = 300


class EvidenceInputError(ValueError):
    """The request cannot produce honest evidence (HTTP 422)."""


class EvidenceContractError(RuntimeError):
    """Produced or received evidence violates evidence_v1 (fail closed)."""


@dataclass(frozen=True)
class SourceInfo:
    session_id: str
    provider: str | None = None
    session_type: str | None = None
    season: int | None = None
    event: str | None = None
    circuit: str | None = None


# -------------------------------------------------------------- validation


def validate_request(*, driver_a: int, lap_a: int, driver_b: int, lap_b: int,
                     lap_length_m: float, lap_length_source: str,
                     contract_version: str = CONTRACT_VERSION) -> None:
    if contract_version not in SUPPORTED_CONTRACTS:
        raise EvidenceInputError(f"unsupported contract_version {contract_version!r}; "
                                 f"supported: {', '.join(SUPPORTED_CONTRACTS)}")
    for name, d in (("driver_a", driver_a), ("driver_b", driver_b)):
        if not 1 <= d <= 99:
            raise EvidenceInputError(f"{name} must be a car number 1-99, got {d}")
    for name, n in (("lap_a", lap_a), ("lap_b", lap_b)):
        if n < 1:
            raise EvidenceInputError(f"{name} must be >= 1, got {n}")
    if (driver_a, lap_a) == (driver_b, lap_b):
        raise EvidenceInputError("driver_a/lap_a and driver_b/lap_b are the same lap")
    if not math.isfinite(lap_length_m) or lap_length_m <= 0:
        raise EvidenceInputError("lap_length_m must be a finite number > 0 (never guessed)")
    src = lap_length_source.strip() if isinstance(lap_length_source, str) else ""
    if not src or len(src) > MAX_SOURCE_CHARS or any(ord(c) < 32 for c in src):
        raise EvidenceInputError(f"lap_length_source must be a printable citation of 1-"
                                 f"{MAX_SOURCE_CHARS} characters")


def _validate_inputs(lap_a: Lap, samples_a: list[TelemetryCarSample], lap_b: Lap,
                     samples_b: list[TelemetryCarSample], source: SourceInfo) -> None:
    for lap, samples in ((lap_a, samples_a), (lap_b, samples_b)):
        who = f"driver {lap.driver_number} lap {lap.lap_number}"
        if lap.session_id != source.session_id:
            raise EvidenceInputError(f"{who} belongs to session {lap.session_id!r}, not "
                                     f"{source.session_id!r} (cross-session comparison)")
        if lap.duration_s is None:
            raise EvidenceInputError(f"{who} has no duration: a completed lap is required")
        if not samples:
            raise EvidenceInputError(f"{who} has no telemetry")
        wrong = [s for s in samples
                 if s.session_id != lap.session_id or s.driver_number != lap.driver_number]
        if wrong:
            raise EvidenceInputError(f"{who}: {len(wrong)} telemetry samples belong to another "
                                     f"driver/session (identity guard)")


def input_digest(lap_a: Lap, samples_a: list[TelemetryCarSample], lap_b: Lap,
                 samples_b: list[TelemetryCarSample]) -> str:
    """sha256 over the canonical input rows: changed data -> changed evidence_id."""
    def lap_key(lap: Lap) -> list:
        return [lap.session_id, lap.driver_number, lap.lap_number, lap.started_at.isoformat(),
                lap.duration_s, lap.sector1_s, lap.sector2_s, lap.sector3_s]

    def rows(samples: list[TelemetryCarSample]) -> list:
        return [[s.ts.isoformat(), s.rpm, s.speed_kph, s.gear, s.throttle_pct, s.brake_pct,
                 s.drs] for s in samples]

    blob = json.dumps([lap_key(lap_a), rows(samples_a), lap_key(lap_b), rows(samples_b)],
                      separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------- mapping


def _exact(obj: Any) -> Any:
    """Enum -> value, tuple -> list, dataclass -> dict. Floats pass through
    UNROUNDED: presentation rounding belongs to the consumer."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _exact(dataclasses.asdict(obj))
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(_exact(k)): _exact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_exact(v) for v in obj]
    return obj


def _driver_block(lap: Lap, trace: LapDistanceTrace, channels: dict[str, bool]) -> dict:
    pts = trace.points
    return {
        "driver_number": lap.driver_number, "lap_number": lap.lap_number,
        "lap_duration_s": lap.duration_s, "started_at": lap.started_at.isoformat(),
        "telemetry": {
            "sample_count": len(pts),
            "x_first": pts[0].normalized_distance if pts else None,
            "x_last": pts[-1].normalized_distance if pts else None,
            "integrated_distance_m": trace.total_distance_m,
            "complete": trace.is_complete, "confidence": trace.confidence.value,
            "channels": dict(channels),
        },
    }


def _references(report: AttributionReport, seg) -> list[dict]:
    out = []
    for driver, lap, rng in ((report.driver_a, report.lap_a, seg.provenance.ts_range_a),
                             (report.driver_b, report.lap_b, seg.provenance.ts_range_b)):
        if rng is not None:
            out.append({"driver_number": driver, "lap_number": lap,
                        "route": TELEMETRY_ROUTE.format(session_id=report.session_id,
                                                        driver_number=driver),
                        "start": rng[0], "end": rng[1]})
    return out


def _segment(report: AttributionReport, eid: str, seg) -> dict:
    no_data = seg.kind is SegmentKind.NO_DATA
    return {
        "segment_id": segment_id_for(eid, seg.start_index, seg.end_index),
        "label": seg.region_id,
        "grid_start_index": seg.start_index, "grid_end_index": seg.end_index,
        "x_start": seg.x_start, "x_end": seg.x_end,
        "distance_start_m": seg.distance_start_m, "distance_end_m": seg.distance_end_m,
        "direction": seg.kind.value,
        "inherited_gap_s": seg.inherited_gap_s,
        "accumulated_change_s": seg.accumulated_change_s,
        "delta_end_s": seg.delta_end_s,
        "uncertainty_s": seg.uncertainty_s,
        "significant": seg.significant,
        "attribution_status": seg.status.value,
        "primary_signal": seg.primary_signal,
        "supporting_signals": list(seg.supporting_signals),
        "onset_order": _exact(seg.onset_order),
        "accumulation_midpoint_x": seg.accumulation_midpoint_x,
        "braking": _exact(seg.braking) if seg.braking is not None else None,
        "throttle": _exact(seg.throttle) if seg.throttle is not None else None,
        "speed": _exact(seg.speed) if seg.speed is not None else None,
        "gear": _exact(seg.gear), "drs": _exact(seg.drs),
        "phase_accumulation_a": dict(seg.phase_accumulation_a),
        "phase_accumulation_b": dict(seg.phase_accumulation_b),
        "dominant_phase_a": seg.dominant_phase_a,
        "telemetry_confidence": seg.confidence.value,
        "association": ASSOCIATION,
        "provenance_class": "F" if no_data else "C",
        "provenance": {
            "delta_source": "10.2 DeltaSample.delta_t_s",
            "grid_indices": list(seg.provenance.grid_indices),
            "sample_indices_a": list(seg.provenance.sample_indices_a),
            "sample_indices_b": list(seg.provenance.sample_indices_b),
            "ts_range_a": _exact(seg.provenance.ts_range_a),
            "ts_range_b": _exact(seg.provenance.ts_range_b),
        },
        "telemetry_references": _references(report, seg),
    }


def evidence_from_report(report: AttributionReport, comparison: DriverLapComparison,
                         lap_a: Lap, lap_b: Lap, *, source: SourceInfo, lap_length_source: str,
                         digest: str) -> LapComparisonEvidenceV1:
    """Map one 10.4 report to evidence_v1 and validate it (fail closed)."""
    if report.calc_version not in SUPPORTED_ATTRIBUTION_VERSIONS:
        raise EvidenceContractError(f"attribution {report.calc_version!r} is not a version this "
                                    f"builder maps ({', '.join(SUPPORTED_ATTRIBUTION_VERSIONS)})")
    identities = {
        "report session": report.session_id, "comparison session": comparison.session_id,
        "lap A session": lap_a.session_id, "lap B session": lap_b.session_id,
    }
    if set(identities.values()) != {source.session_id}:
        raise EvidenceContractError(f"session identity mismatch: {identities} vs "
                                    f"source {source.session_id!r}")
    from_report = (report.driver_a, report.lap_a, report.driver_b, report.lap_b)
    from_laps = (lap_a.driver_number, lap_a.lap_number, lap_b.driver_number, lap_b.lap_number)
    from_cmp = (comparison.driver_a, comparison.lap_number_a, comparison.driver_b,
                comparison.lap_number_b)
    if from_report != from_laps or from_laps != from_cmp:
        raise EvidenceContractError(f"driver/lap identity differs: report {from_report}, "
                                    f"laps {from_laps}, comparison {from_cmp}")

    eid = evidence_id_for(
        contract_version=CONTRACT_VERSION, attribution_version=report.calc_version,
        lap_distance_version=LAP_DISTANCE_VERSION, session_id=source.session_id,
        driver_a=report.driver_a, lap_a=report.lap_a, driver_b=report.driver_b,
        lap_b=report.lap_b, lap_length_m=report.lap_length_m,
        lap_length_source=lap_length_source.strip(), input_digest=digest)
    label_to_id = {s.region_id: segment_id_for(eid, s.start_index, s.end_index)
                   for s in report.segments}
    u = report.uncertainty
    acc = report.accounting
    payload = {
        "contract_version": CONTRACT_VERSION,
        "evidence_type": "lap_comparison",
        "evidence_id": eid,
        "calculation": {"contract_version": CONTRACT_VERSION,
                        "evidence_builder_version": BUILDER_VERSION,
                        "attribution_version": report.calc_version,
                        "lap_distance_version": LAP_DISTANCE_VERSION},
        "source": dataclasses.asdict(source),
        "comparison": {
            "driver_a": _driver_block(lap_a, comparison.trace_a, report.channels["a"]),
            "driver_b": _driver_block(lap_b, comparison.trace_b, report.channels["b"]),
            "lap_delta_s": report.official_lap_delta_s,
            "lap_delta_provenance_class": "B" if report.official_lap_delta_s is not None else "F",
            "engine_delta_last_covered_s": report.engine_delta_last_covered_s,
            "last_covered_x": report.last_covered_x,
            "sign_convention": report.sign_convention,
            "lap_length": {"m": report.lap_length_m, "source": lap_length_source.strip()},
            "alignment": {
                "mode": report.alignment_mode.value,
                "misalignment_bound_m": u.misalignment_bound_m,
                "within_segment_change_bound_m": u.change_bound_m,
                "uncertainty_source": u.source,
                "anchors": [{"line": a.sector, "distance_a_m": a.distance_a_m,
                             "distance_b_m": a.distance_b_m, "misalignment_m": a.misalignment_m}
                            for a in u.anchors],
            },
            "telemetry_confidence": report.comparison_confidence.value,
        },
        "attribution": {
            "segments": [_segment(report, eid, s) for s in report.segments],
            "accounting": {
                "actual_change_s": acc.actual_change_s,
                "attributed_change_s": acc.attributed_change_s,
                "unattributed_significant_change_s": acc.unattributed_significant_change_s,
                "below_significance_change_s": acc.below_significance_change_s,
                "unaccounted_s": acc.unaccounted_s,
                "change_by_status": dict(acc.change_by_status),
                "no_data_spans": _exact(acc.no_data_spans),
            },
            "sectors": [{
                "sector_id": sector_id_for(eid, sec.sector), "sector": sec.sector,
                "official_a_s": sec.official_a_s, "official_b_s": sec.official_b_s,
                "official_delta_s": sec.official_delta_s,
                "official_provenance_class": "B" if sec.official_delta_s is not None else "F",
                "engine_change_s": sec.engine_change_s,
                "engine_minus_official_s": sec.engine_minus_official_s,
                "engine_provenance_class": "C" if sec.engine_change_s is not None else "F",
                "coverage": "COVERED" if sec.engine_change_s is not None else "NOT_COVERED",
                "line_x_a": sec.line_x_a, "line_x_b": sec.line_x_b,
                "line_misalignment_m": sec.line_misalignment_m,
                "segment_ids": [label_to_id[r] for r in sec.segment_ids],
            } for sec in report.sectors],
        },
        "limitations": [{"code": x.code, "message": x.message} for x in report.limitation_items],
        "provenance": {
            "chain": [
                f"{CONTRACT_VERSION} ({BUILDER_VERSION}, app.evidence.lap_comparison)",
                f"{report.calc_version} (app.analysis.attribution)",
                "10.2 app.analysis.delta_analysis DeltaSample.delta_t_s",
                f"{LAP_DISTANCE_VERSION} (app.analysis.lap_distance, 10.1B/10.1C)",
                "canonical app.core.models Lap / TelemetryCarSample",
                f"{source.provider or 'unknown'} provider rows (identity-guarded)",
            ],
            "input_digest": digest,
            "identity_checks": [
                "each lap.session_id == source.session_id",
                "each telemetry sample's session_id and driver_number == its lap's",
                "10.1B synchronize_drivers: both traces from the same session",
                "report, laps and comparison agree on driver and lap numbers",
            ],
            "laps": [_lap_provenance(lap, trace) for lap, trace in (
                (lap_a, comparison.trace_a), (lap_b, comparison.trace_b))],
        },
    }
    try:
        text = json.dumps(payload, allow_nan=False)
    except ValueError as exc:
        raise EvidenceContractError(f"non-finite number in evidence: {exc}") from exc
    try:
        return LapComparisonEvidenceV1.model_validate_json(text)
    except ValidationError as exc:
        raise EvidenceContractError(f"evidence failed {CONTRACT_VERSION} validation: "
                                    f"{exc.errors()[0]['msg']}") from exc


def _lap_provenance(lap: Lap, trace: LapDistanceTrace) -> dict:
    pts = trace.points
    return {"driver_number": lap.driver_number, "lap_number": lap.lap_number,
            "session_id": lap.session_id, "lap_started_at": lap.started_at.isoformat(),
            "telemetry_first_ts": pts[0].ts.isoformat() if pts else None,
            "telemetry_last_ts": pts[-1].ts.isoformat() if pts else None,
            "sample_count": len(pts)}


def build_lap_comparison_evidence(
        lap_a: Lap, samples_a: list[TelemetryCarSample], lap_b: Lap,
        samples_b: list[TelemetryCarSample], *, lap_length_m: float, lap_length_source: str,
        source: SourceInfo, contract_version: str = CONTRACT_VERSION,
) -> LapComparisonEvidenceV1:
    """Canonical rows -> 10.1B -> 10.1C -> 10.2 -> 10.4 -> evidence_v1."""
    validate_request(driver_a=lap_a.driver_number, lap_a=lap_a.lap_number,
                     driver_b=lap_b.driver_number, lap_b=lap_b.lap_number,
                     lap_length_m=lap_length_m, lap_length_source=lap_length_source,
                     contract_version=contract_version)
    _validate_inputs(lap_a, samples_a, lap_b, samples_b, source)
    try:
        comparison = compare_driver_laps(lap_a, samples_a, None, lap_b, samples_b, None,
                                         lap_length_m=lap_length_m)
    except ValueError as exc:  # e.g. 10.1B refuses cross-session synchronization
        raise EvidenceInputError(str(exc)) from exc
    report = attribute_comparison(analyze_delta(comparison), lap_a, lap_b)
    return evidence_from_report(report, comparison, lap_a, lap_b, source=source,
                                lap_length_source=lap_length_source,
                                digest=input_digest(lap_a, samples_a, lap_b, samples_b))


# ----------------------------------------------------------- serialization


def to_canonical_json(evidence: LapComparisonEvidenceV1) -> bytes:
    """Canonical bytes: sorted keys, no whitespace, UTF-8, shortest-repr floats,
    no NaN. Identical evidence -> identical bytes."""
    return json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def parse_evidence(raw: bytes | str | dict) -> LapComparisonEvidenceV1:
    """Consumer-side: parse + validate. Unsupported versions are refused."""
    data = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    version = data.get("contract_version") if isinstance(data, dict) else None
    if version not in SUPPORTED_CONTRACTS:
        raise EvidenceContractError(f"unsupported contract_version {version!r}")
    try:
        return LapComparisonEvidenceV1.model_validate_json(
            json.dumps(data, allow_nan=False))
    except (ValidationError, ValueError) as exc:
        raise EvidenceContractError(f"payload is not valid {CONTRACT_VERSION}: {exc}") from exc
