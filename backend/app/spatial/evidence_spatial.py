"""Phase 12C: evidence_v1 segments placed on the validated 12A track by time.

evidence_v1 measures along a NORMALIZED distance axis (integrated speed
divided by the cited length): never a track position. This module places a
segment on the track without that axis. For each driver it takes the
segment's own provenance ts_range - that driver's first and last real
samples inside the segment - and reads the driver's 12A state at those two
times. When both are on the reference with a lap fraction, the extent runs
forward from the first fraction to the second along the reference.
Otherwise the extent is NOT_PLACED with the reason; nothing is derived.
"""

from __future__ import annotations

from datetime import datetime

from app.spatial import builder
from app.spatial.contract import (
    EVIDENCE_SPATIAL_CONTRACT,
    EvidenceSpatialV1,
    SpatialContractError,
    _validate,
)
from app.spatial.state import SpatialIndex, driver_state

BUILDER_VERSION = "evidence-spatial-1.0.0"
CONTRACT = EVIDENCE_SPATIAL_CONTRACT
# The reason reported when both ends fail: the first in this order.
_REASON_ORDER = ("NO_COVERAGE", "STALE", "PIT_LANE", "OFF_REFERENCE", "NO_FRACTION")
_MESSAGES = {
    "SEGMENT_PLACED_BY_TIME": "Each driver's extent runs between that driver's 12A positions at "
                              "its own first and last sample times in the segment.",
    "EVIDENCE_DISTANCE_NORMALIZED_NOT_POSITION": "Evidence metres are integrated distance "
                                                 "normalized to the cited length; they never "
                                                 "place anything on the track.",
    "EXTENT_IS_SAMPLE_BOUNDED": "An extent starts and ends at real samples, so consecutive "
                                "extents leave the stretch between two samples uncovered.",
}


def _lim(code: str) -> dict:
    message = _MESSAGES.get(code) or builder._MESSAGES[code]
    return {"code": code, "message": message}


def _reason(entry: dict | None) -> str | None:
    if entry is None or entry["status"] == "NO_COVERAGE":
        return "NO_COVERAGE"
    if entry["status"] == "STALE":
        return "STALE"
    if entry["flag"] in ("PIT_LANE", "OFF_REFERENCE"):
        return entry["flag"]
    return "NO_FRACTION" if entry["reference_fraction"] is None else None


def _not_placed(reason: str, from_ts: str | None, to_ts: str | None) -> dict:
    return {"status": "NOT_PLACED", "reason": reason, "from_ts": from_ts, "to_ts": to_ts,
            "from_fraction": None, "to_fraction": None, "from_xy": None, "to_xy": None,
            "polyline": None}


def _extent(index: SpatialIndex, driver: int, ts_range: list[str] | None) -> dict:
    if ts_range is None:
        return _not_placed("NO_TELEMETRY", None, None)
    from_ts, to_ts = ts_range
    ends = [driver_state(index, driver, datetime.fromisoformat(ts).timestamp())
            for ts in (from_ts, to_ts)]
    reasons = [r for r in map(_reason, ends) if r is not None]
    if reasons:
        return _not_placed(min(reasons, key=_REASON_ORDER.index), from_ts, to_ts)
    e0, e1 = ends
    f0, f1 = e0["reference_fraction"], e1["reference_fraction"]
    line = index.centerline
    # the same arc-length mapping the 12A state uses for its own x/y
    s0 = ((f0 + index.finish_fraction) % 1.0) * line.total_length
    s1 = ((f1 + index.finish_fraction) % 1.0) * line.total_length
    return {"status": "PLACED", "reason": None, "from_ts": from_ts, "to_ts": to_ts,
            "from_fraction": f0, "to_fraction": f1, "from_xy": [e0["x"], e0["y"]],
            "to_xy": [e1["x"], e1["y"]],
            "polyline": [[x, y] for x, y in line.subpath(s0, s1)]}


def place_evidence(evidence: dict, index: SpatialIndex) -> dict:
    """evidence_spatial_v1 for one evidence_v1 document (as a JSON dict)."""
    comparison = evidence["comparison"]
    da = comparison["driver_a"]["driver_number"]
    db = comparison["driver_b"]["driver_number"]
    segments = []
    for seg in evidence["attribution"]["segments"]:
        prov = seg.get("provenance") or {}
        no_data = seg.get("attribution_status") == "NO_DATA"
        segments.append({"segment_id": seg["segment_id"], "label": seg["label"],
                         "a": _extent(index, da, None if no_data else prov.get("ts_range_a")),
                         "b": _extent(index, db, None if no_data else prov.get("ts_range_b"))})
    codes = ["SEGMENT_PLACED_BY_TIME", "EVIDENCE_DISTANCE_NORMALIZED_NOT_POSITION",
             "EXTENT_IS_SAMPLE_BOUNDED", "INTERPOLATED_BETWEEN_SAMPLES"]
    if not index.corner_precision_met:
        codes.append("CORNER_PRECISION_NOT_MET")
    doc = {"contract_version": CONTRACT, "builder_version": BUILDER_VERSION,
           "evidence_id": evidence["evidence_id"], "session_id": index.session_id,
           "track_id": index.track_id, "driver_a": da, "driver_b": db,
           "lap_length_m": index.lap_length_m, "line_placement_p95_m": index.line_p95_m,
           "segments": segments, "limitations": [_lim(c) for c in sorted(codes)]}
    validate_evidence_spatial(doc, evidence)
    return doc


def validate_evidence_spatial(doc: dict, evidence: dict) -> None:
    """The contract, plus agreement with the evidence it places (fail closed)."""
    _validate(EvidenceSpatialV1, doc)
    comparison = evidence["comparison"]
    problems = []
    if doc["evidence_id"] != evidence["evidence_id"]:
        problems.append("evidence_id differs from the evidence")
    if doc["session_id"] != evidence["source"]["session_id"]:
        problems.append("session differs from the evidence")
    if (doc["driver_a"], doc["driver_b"]) != (comparison["driver_a"]["driver_number"],
                                              comparison["driver_b"]["driver_number"]):
        problems.append("drivers differ from the evidence")
    segs = evidence["attribution"]["segments"]
    if [(s["segment_id"], s["label"]) for s in doc["segments"]] != \
            [(s["segment_id"], s["label"]) for s in segs]:
        problems.append("segments differ from the evidence (ids, labels or order)")
    else:
        for placed, seg in zip(doc["segments"], segs, strict=True):
            prov = seg.get("provenance") or {}
            no_data = seg.get("attribution_status") == "NO_DATA"
            for side in ("a", "b"):
                rng = None if no_data else prov.get(f"ts_range_{side}")
                ext = placed[side]
                got = None if ext["from_ts"] is None else [ext["from_ts"], ext["to_ts"]]
                if got != (None if rng is None else list(rng)):
                    problems.append(f"{seg['label']} {side}: times are not the segment's own")
    if problems:
        raise SpatialContractError("; ".join(problems))
