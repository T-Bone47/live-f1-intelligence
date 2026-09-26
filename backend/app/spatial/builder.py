"""Phase 12A: build the spatial evidence of one session.

source -> reference -> timing lines -> gate -> tolerance / pit windows ->
sample classification -> track_reference_v1 (+ the in-memory index that
answers spatial_state_v1 / spatial_trace_v1). Geometry that fails the
MAP_SECTOR gate is published with its validation but without a polyline or
an index: nothing downstream can place a car on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.spatial.circuits import CitedLength, cited_lap_length
from app.spatial.contract import (
    SPATIAL_BUILDER_VERSION,
    STATE_CONTRACT,
    TRACE_CONTRACT,
    TRACK_CONTRACT,
    make_track_id,
    validate_state,
    validate_trace,
    validate_track,
)
from app.spatial.gate import evaluate_gate
from app.spatial.reference import (
    build_reference,
    eligible_laps,
    reference_candidates,
)
from app.spatial.samples import (
    PIT_INSIDE_MAX_SHARE,
    choose_pit_mode,
    classify_driver,
    derive_tolerance,
    inside_share,
    pit_windows,
)
from app.spatial.source import SpatialInputs
from app.spatial.state import SpatialIndex, empty_track, iso, state_at, trace, track_from_samples
from app.spatial.timing_lines import LINES, measure_lines, reference_independence_m

CHAIN = [
    "OpenF1 /location, /laps, /pit rows in the session recording (identity-guarded)",
    "canonical TelemetryLocationSample, Lap, PitStop",
    "deterministic reference lap -> closed Centerline (Phase 10.3 projection)",
    "official lap and sector timestamps -> measured timing lines",
    "claim-scoped gate (MAP_SECTOR p95 <= 20 m, CORNER p95 <= 5 m)",
    "sample classification: PIT_LANE / OFF_REFERENCE / ON_REFERENCE",
    SPATIAL_BUILDER_VERSION,
]

_MESSAGES = {
    "FEED_LINE_NOT_RACING_LINE": "The location feed reports every car on one shared line: "
                                 "there is no lateral or racing-line information.",
    "METRES_NORMALIZED_TO_CITED_LENGTH": "Metres are the lap fraction from the measured finish "
                                         "line times the cited lap length, not surveyed distance.",
    "UNITS_UNDOCUMENTED": "Feed coordinates have an arbitrary origin and an undocumented unit; "
                          "the units-per-metre ratio is measured, never used for metres.",
    "CORNER_PRECISION_NOT_MET": "Timing lines land further apart than the 5 m corner gate: "
                                "no corner-level metre claims.",
    "CORNERS_UNAVAILABLE": "No licensed or verified corner source: no corner names, numbers "
                           "or apexes.",
    "DRS_DATA_ABSENT": "The DRS channel is null in every car sample of this session.",
    "PIT_LANE_GEOMETRY_UNAVAILABLE": "Pit lane is a sample flag, not a path.",
    "INTERPOLATED_BETWEEN_SAMPLES": "Positions at a time lie between two real samples of the "
                                    "same driver (bracket given); nothing is extrapolated.",
    "RECORDING_ONLY": "Built from the session recording; a running live session is not "
                      "spatialized.",
}


def _lim(code: str) -> dict:
    return {"code": code, "message": _MESSAGES[code]}


def _gate_doc(g) -> dict:
    return {"claim": g.claim, "passed": g.passed, "threshold_m": g.threshold_m,
            "observed_p95_m": g.observed_p95_m, "reasons": list(g.reasons)}


def _line_doc(m, finish_fraction: float | None, length: float | None, validated: bool) -> dict:
    """Unvalidated geometry publishes the measurement (n, exclusions,
    dispersion, worst) but no position on the track (spec 5.4)."""
    distance = None
    if validated and length is not None and finish_fraction is not None:
        distance = ((m.fraction - finish_fraction) % 1.0) * length
        distance = 0.0 if m.line == "FINISH" else distance
    unit = "m" if length is not None else "fraction"
    return {"line": m.line, "loop_fraction": m.fraction if validated else None,
            "distance_m": distance, "x": m.x if validated else None,
            "y": m.y if validated else None, "n": m.n, "exclusions": dict(m.exclusions),
            "dispersion_m": None if m.dispersion_m is None else dict(m.dispersion_m),
            "dispersion_fraction": dict(m.dispersion_fraction),
            "worst": [{"driver_number": d, "lap_number": lap, "value": v, "unit": unit}
                      for d, lap, v in m.worst]}


def _capabilities(inputs: SpatialInputs, lateral: dict[str, float]) -> dict:
    counts = inputs.counts
    return {
        "racing_line": {"available": False, "reason": _MESSAGES["FEED_LINE_NOT_RACING_LINE"],
                        "evidence": dict(lateral)},
        "drs_zones": {"available": False,
                      "reason": "No DRS zone geometry source; the DRS channel is reported "
                                "in the evidence counts.",
                      "evidence": {"car_samples": counts.get("car_samples"),
                                   "drs_null": counts.get("car_drs_null")}},
        "corners": {"available": False, "reason": _MESSAGES["CORNERS_UNAVAILABLE"], "evidence": {}},
        "pit_lane_geometry": {"available": False,
                              "reason": _MESSAGES["PIT_LANE_GEOMETRY_UNAVAILABLE"], "evidence": {}},
    }


def build_spatial(inputs: SpatialInputs,
                  circuits: Mapping[str, CitedLength] | None = None
                  ) -> tuple[dict, SpatialIndex | None]:
    session = inputs.session
    cited = cited_lap_length(session.get("circuit_short_name"), circuits)
    length = None if cited is None else cited.lap_length_m
    track_id = make_track_id(inputs.session_id, inputs.input_digest, cited)
    candidates = reference_candidates(inputs, k=3)

    reference_doc, lines_doc, tolerance_doc, pit_doc = None, [], None, None
    lateral: dict[str, float] = {}
    index, reasons = None, []
    if not candidates:
        gates = evaluate_gate(None, None, cited)
        reasons = ["NO_ELIGIBLE_REFERENCE_LAP"]
        independence = None
    else:
        refs = [build_reference(inputs, c) for c in candidates]
        ref = refs[0]
        lines = measure_lines(inputs, ref, length)
        independence = reference_independence_m(inputs, refs, length)
        gates = evaluate_gate(lines, independence, cited)
        tol, lateral, n_green = derive_tolerance(inputs, ref,
                                                 eligible_laps(inputs, require_coverage=False))
        pit = choose_pit_mode(inputs, ref, tol)
        windows = [] if pit.mode == "NONE" else pit_windows(inputs, pit.mode)
        probe = windows or pit_windows(inputs, "ENTRY") + pit_windows(inputs, "EXIT")
        share, _n = inside_share(inputs, ref, tol, probe)
        tolerance_doc = {"feed_units": tol, "n": n_green, "lateral_percentiles": dict(lateral),
                         "pit_inside_share": share,
                         "provisional": share is None or share >= PIT_INSIDE_MAX_SHARE}
        pit_doc = {"mode": pit.mode, "share_entry": pit.share_entry, "share_exit": pit.share_exit,
                   "samples_entry": pit.samples_entry, "samples_exit": pit.samples_exit}
        finish = lines["FINISH"].fraction if "FINISH" in lines else None
        validated = gates["MAP_SECTOR"].passed and finish is not None
        lines_doc = [_line_doc(lines[name], finish, length, validated)
                     for name in LINES if name in lines]
        reference_doc = {"driver_number": ref.driver, "lap_number": ref.lap,
                         "started_at": iso(ref.start), "duration_s": ref.duration,
                         "point_count": len(ref.points),
                         "loop_length_feed_units": ref.centerline.total_length,
                         "polyline": [list(p) for p in ref.points] if validated else None}
        if validated:
            drivers = sorted(set(inputs.drivers) | set(inputs.samples))
            tracks = {d: (track_from_samples(classify_driver(inputs, d, ref, finish, tol, windows))
                          if d in inputs.samples else empty_track()) for d in drivers}
            index = SpatialIndex(session_id=inputs.session_id, track_id=track_id,
                                 ref_points=ref.points, finish_fraction=finish,
                                 lap_length_m=length, tracks=tracks,
                                 line_p95_m=None if length is None else
                                 {m.line: m.dispersion_m["p95"] for m in lines.values()},
                                 corner_precision_met=gates["CORNER"].passed)
        else:
            reasons = list(gates["MAP_SECTOR"].reasons)

    codes = ["FEED_LINE_NOT_RACING_LINE", "UNITS_UNDOCUMENTED", "CORNERS_UNAVAILABLE",
             "PIT_LANE_GEOMETRY_UNAVAILABLE", "RECORDING_ONLY"]
    if cited is not None:
        codes.append("METRES_NORMALIZED_TO_CITED_LENGTH")
    if not gates["CORNER"].passed:
        codes.append("CORNER_PRECISION_NOT_MET")
    car, null = inputs.counts.get("car_samples"), inputs.counts.get("car_drs_null")
    if car and car == null:
        codes.append("DRS_DATA_ABSENT")

    loop = None if reference_doc is None else reference_doc["loop_length_feed_units"]
    doc = {
        "contract_version": TRACK_CONTRACT, "builder_version": SPATIAL_BUILDER_VERSION,
        "track_id": track_id, "status": "VALIDATED_MAP_SECTOR" if index else "UNVALIDATED",
        "session": {"session_id": inputs.session_id,
                    "circuit_short_name": session.get("circuit_short_name"),
                    "session_type": session.get("session_type"), "year": session.get("year"),
                    "date_start": session.get("date_start")},
        "circuit": {"short_name": session.get("circuit_short_name"), "lap_length_m": length,
                    "lap_length_source": None if cited is None else cited.source},
        "coordinate_system": {"kind": "OPENF1_LOCATION_FEED", "units": "undocumented",
                              "origin": "arbitrary",
                              "measured_units_per_metre": None if loop is None or length is None
                              else loop / length},
        "reference": reference_doc,
        "timing_lines": lines_doc,
        "validation": {"gates": {k: _gate_doc(g) for k, g in gates.items()},
                       "reference_independence_m": independence,
                       "on_reference_tol": tolerance_doc, "pit_windows": pit_doc,
                       "reasons": reasons},
        "capabilities": _capabilities(inputs, lateral),
        "limitations": [_lim(c) for c in sorted(codes)],
        "provenance": {"chain": CHAIN, "input_digest": inputs.input_digest,
                       "counts": dict(sorted(inputs.counts.items())),
                       "reference_candidates": [{"driver_number": c.driver, "lap_number": c.lap,
                                                 "duration_s": c.duration} for c in candidates]},
    }
    validate_track(doc)
    return doc, index


def _doc_limitations(index: SpatialIndex) -> list[dict]:
    codes = ["FEED_LINE_NOT_RACING_LINE", "INTERPOLATED_BETWEEN_SAMPLES", "RECORDING_ONLY"]
    if index.lap_length_m is not None:
        codes.append("METRES_NORMALIZED_TO_CITED_LENGTH")
    if not index.corner_precision_met:
        codes.append("CORNER_PRECISION_NOT_MET")
    return [_lim(c) for c in sorted(codes)]


def state_doc(index: SpatialIndex, at: datetime) -> dict:
    """spatial_state_v1 for every driver at `at` (an aware datetime)."""
    doc = {"contract_version": STATE_CONTRACT, "builder_version": SPATIAL_BUILDER_VERSION,
           "session_id": index.session_id, "track_id": index.track_id,
           "at": at.astimezone(UTC).isoformat(), "lap_length_m": index.lap_length_m,
           "line_placement_p95_m": index.line_p95_m,
           "drivers": state_at(index, at.timestamp()), "limitations": _doc_limitations(index)}
    validate_state(doc)
    return doc


def trace_doc(index: SpatialIndex, driver: int, t0: datetime, t1: datetime) -> dict:
    """spatial_trace_v1: one driver's classified samples in [t0, t1]."""
    doc = {"contract_version": TRACE_CONTRACT, "builder_version": SPATIAL_BUILDER_VERSION,
           "session_id": index.session_id, "track_id": index.track_id, "driver_number": driver,
           "from_ts": t0.astimezone(UTC).isoformat(), "to_ts": t1.astimezone(UTC).isoformat(),
           "lap_length_m": index.lap_length_m, "line_placement_p95_m": index.line_p95_m,
           "samples": trace(index, driver, t0.timestamp(), t1.timestamp()),
           "limitations": _doc_limitations(index)}
    validate_trace(doc)
    return doc
