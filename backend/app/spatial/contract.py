"""Phase 12A spatial contracts: track_reference_v1, spatial_state_v1,
spatial_trace_v1.

Strict, fail-closed pydantic models (the evidence_v1 conventions: unknown
fields, NaN/Infinity and wrong types are rejected) plus cross-field rules
that keep every document honest: no polyline on unvalidated geometry, no lap
fraction off the reference line, no metres without a cited lap length, and a
track_id recomputed from its own content.
"""

from __future__ import annotations

import hashlib
import json
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.spatial.circuits import CitedLength

SPATIAL_BUILDER_VERSION = "spatial-builder-1.0.0"
TRACK_CONTRACT = "track_reference_v1"
STATE_CONTRACT = "spatial_state_v1"
TRACE_CONTRACT = "spatial_trace_v1"

Flag = Literal["ON_REFERENCE", "PIT_LANE", "OFF_REFERENCE"]
Grade = Literal["HIGH", "MEDIUM", "LOW", "NONE"]


class SpatialContractError(ValueError):
    """A spatial document failed its contract; it must be withheld."""


def make_track_id(session_id: str, input_digest: str, cited: CitedLength | None) -> str:
    """Content id: same data, builder and citation -> same id."""
    parts = [SPATIAL_BUILDER_VERSION, session_id, input_digest,
             None if cited is None else cited.lap_length_m, None if cited is None else cited.source]
    digest = hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()
    return "trk1_" + digest[:24]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class Limitation(_M):
    code: str
    message: str


class Gate(_M):
    claim: Literal["MAP_SECTOR", "CORNER"]
    passed: bool
    threshold_m: float
    observed_p95_m: dict[str, float | None]
    reasons: list[str]


class Dispersion(_M):
    median: float
    p90: float
    p95: float
    p99: float
    max: float


class Worst(_M):
    driver_number: int
    lap_number: int
    value: float
    unit: Literal["m", "fraction"]


class TimingLine(_M):
    line: Literal["FINISH", "S1", "S2"]
    loop_fraction: float | None
    distance_m: float | None
    x: float | None
    y: float | None
    n: int
    exclusions: dict[str, int]
    dispersion_m: Dispersion | None
    dispersion_fraction: Dispersion
    worst: list[Worst]


LineName = Literal["FINISH", "S1", "S2"]
SECTOR_LINES = (("FINISH", "S1"), ("S1", "S2"), ("S2", "FINISH"))
SECTOR_LENGTH_TOL_M = 1e-6


class SectorGeometry(_M):
    sector: Literal[1, 2, 3]
    from_line: LineName
    to_line: LineName
    length_m: float
    polyline: list[list[float]]
    label_point: list[float]


class Session(_M):
    session_id: str
    circuit_short_name: str | None
    session_type: str | None
    year: int | None
    date_start: str | None


class Circuit(_M):
    short_name: str | None
    lap_length_m: float | None
    lap_length_source: str | None


class CoordinateSystem(_M):
    kind: Literal["OPENF1_LOCATION_FEED"]
    units: Literal["undocumented"]
    origin: Literal["arbitrary"]
    measured_units_per_metre: float | None


class Reference(_M):
    driver_number: int
    lap_number: int
    started_at: str
    duration_s: float
    point_count: int
    loop_length_feed_units: float
    polyline: list[list[float]] | None


class OnReferenceTolerance(_M):
    feed_units: float
    n: int
    lateral_percentiles: dict[str, float]
    pit_inside_share: float | None
    provisional: bool


class PitWindows(_M):
    mode: Literal["ENTRY", "EXIT", "NONE"]
    share_entry: float | None
    share_exit: float | None
    samples_entry: int
    samples_exit: int


class Validation(_M):
    gates: dict[str, Gate]
    reference_independence_m: float | None
    on_reference_tol: OnReferenceTolerance | None
    pit_windows: PitWindows | None
    reasons: list[str]


class Capability(_M):
    available: Literal[False]
    reason: str
    evidence: dict[str, float | int | None]


class Capabilities(_M):
    racing_line: Capability
    drs_zones: Capability
    corners: Capability
    pit_lane_geometry: Capability


class Candidate(_M):
    driver_number: int
    lap_number: int
    duration_s: float


class Provenance(_M):
    chain: list[str]
    input_digest: str
    counts: dict[str, int]
    reference_candidates: list[Candidate]


class TrackReferenceV1(_M):
    contract_version: Literal["track_reference_v1"]
    builder_version: str
    track_id: str
    status: Literal["VALIDATED_MAP_SECTOR", "UNVALIDATED"]
    session: Session
    circuit: Circuit
    coordinate_system: CoordinateSystem
    reference: Reference | None
    timing_lines: list[TimingLine]
    sectors: list[SectorGeometry]
    validation: Validation
    capabilities: Capabilities
    limitations: list[Limitation]
    provenance: Provenance

    @model_validator(mode="after")
    def _rules(self) -> TrackReferenceV1:
        polyline = None if self.reference is None else self.reference.polyline
        if set(self.validation.gates) != {"MAP_SECTOR", "CORNER"}:
            raise ValueError("gates must be exactly MAP_SECTOR and CORNER")
        if self.status == "VALIDATED_MAP_SECTOR":
            if polyline is None or not self.validation.gates["MAP_SECTOR"].passed:
                raise ValueError("validated geometry needs a polyline and a passed MAP_SECTOR gate")
            if any(len(p) != 2 for p in polyline) or polyline[0] != polyline[-1]:
                raise ValueError("polyline must be closed (x, y) pairs")
        elif polyline is not None:
            raise ValueError("unvalidated geometry must not publish a polyline")
        validated = self.status == "VALIDATED_MAP_SECTOR"
        for line in self.timing_lines:
            placed = (line.loop_fraction, line.x, line.y)
            if validated and None in placed:
                raise ValueError(f"validated line {line.line} needs its position")
            if not validated and (any(v is not None for v in placed)
                                  or line.distance_m is not None):
                raise ValueError(f"unvalidated line {line.line} must not publish a position")
        cited = self.circuit.lap_length_m is not None
        if (self.circuit.lap_length_m is None) != (self.circuit.lap_length_source is None):
            raise ValueError("a lap length needs its source")
        for line in self.timing_lines:
            if not cited and (line.distance_m is not None or line.dispersion_m is not None):
                raise ValueError("metres need a cited lap length")
        lines = [line.line for line in self.timing_lines]
        if len(lines) != len(set(lines)):
            raise ValueError("duplicate timing line")
        self._sector_rules(validated)
        expected = make_track_id(
            self.session.session_id, self.provenance.input_digest,
            CitedLength(self.circuit.lap_length_m, self.circuit.lap_length_source)
            if cited else None)
        if self.track_id != expected:
            raise ValueError("track_id does not match its content")
        return self

    def _sector_rules(self, validated: bool) -> None:
        """Phase 12B: three contiguous sector paths, only on validated
        geometry, each running exactly from its start line to its end line,
        their metres adding up to the cited lap."""
        if not validated:
            if self.sectors:
                raise ValueError("unvalidated geometry must not publish sector paths")
            return
        pairs = [(s.sector, s.from_line, s.to_line) for s in self.sectors]
        if pairs != [(k, a, b) for k, (a, b) in enumerate(SECTOR_LINES, start=1)]:
            raise ValueError("sectors must be 1 FINISH->S1, 2 S1->S2, 3 S2->FINISH")
        if self.circuit.lap_length_m is None:
            raise ValueError("sector metres need a cited lap length")
        at = {line.line: [line.x, line.y] for line in self.timing_lines}
        for s in self.sectors:
            if len(s.polyline) < 2 or any(len(p) != 2 for p in s.polyline)                     or len(s.label_point) != 2:
                raise ValueError(f"sector {s.sector}: path must be (x, y) pairs")
            if s.polyline[0] != at.get(s.from_line) or s.polyline[-1] != at.get(s.to_line):
                raise ValueError(f"sector {s.sector}: path must run line to line")
        total = sum(s.length_m for s in self.sectors)
        if abs(total - self.circuit.lap_length_m) > SECTOR_LENGTH_TOL_M:
            raise ValueError("sector lengths must add up to the cited lap length")


class Bracket(_M):
    before: str
    after: str
    gap_s: float


class DriverState(_M):
    driver_number: int
    status: Literal["POSITIONED", "STALE", "NO_COVERAGE"]
    flag: Flag | None
    confidence: Grade | None
    x: float | None
    y: float | None
    reference_fraction: float | None
    distance_m: float | None
    sector: Literal[1, 2, 3] | None
    lap_number: int | None
    bracket: Bracket | None
    age_s: float | None


def _position_rules(flag: str | None, fraction: float | None, distance: float | None,
                    lap_length_m: float | None, sector: int | None) -> None:
    if (sector is None) != (fraction is None):
        raise ValueError("a sector exists exactly when a lap fraction does")
    if fraction is not None and (flag != "ON_REFERENCE" or not 0.0 <= fraction < 1.0):
        raise ValueError("a lap fraction exists only on the reference, in [0, 1)")
    if distance is not None and (fraction is None or lap_length_m is None):
        raise ValueError("metres need a fraction and a cited lap length")


def _ordered_unique(values: list) -> bool:
    return all(a < b for a, b in pairwise(values))


class SpatialStateV1(_M):
    contract_version: Literal["spatial_state_v1"]
    builder_version: str
    session_id: str
    track_id: str
    at: str
    lap_length_m: float | None
    line_placement_p95_m: dict[str, float] | None
    drivers: list[DriverState]
    limitations: list[Limitation]

    @model_validator(mode="after")
    def _rules(self) -> SpatialStateV1:
        if not _ordered_unique([d.driver_number for d in self.drivers]):
            raise ValueError("drivers must be sorted and unique")
        for d in self.drivers:
            values = (d.flag, d.confidence, d.x, d.y, d.reference_fraction, d.distance_m,
                      d.sector, d.lap_number, d.bracket, d.age_s)
            if d.status == "NO_COVERAGE":
                if any(v is not None for v in values):
                    raise ValueError(f"#{d.driver_number}: NO_COVERAGE carries no value")
                continue
            if d.bracket is None or d.x is None or d.y is None or d.flag is None:
                raise ValueError(f"#{d.driver_number}: {d.status} needs x, y, flag and a bracket")
            if (d.status == "STALE") != (d.age_s is not None):
                raise ValueError(f"#{d.driver_number}: age_s exactly when STALE")
            _position_rules(d.flag, d.reference_fraction, d.distance_m, self.lap_length_m,
                            d.sector)
        return self


class TraceSample(_M):
    ts: str
    x: float
    y: float
    flag: Flag
    reference_fraction: float | None
    distance_m: float | None
    sector: Literal[1, 2, 3] | None
    lap_number: int | None
    confidence: Grade


class SpatialTraceV1(_M):
    contract_version: Literal["spatial_trace_v1"]
    builder_version: str
    session_id: str
    track_id: str
    driver_number: int
    from_ts: str
    to_ts: str
    lap_length_m: float | None
    line_placement_p95_m: dict[str, float] | None
    samples: list[TraceSample]
    limitations: list[Limitation]

    @model_validator(mode="after")
    def _rules(self) -> SpatialTraceV1:
        if not _ordered_unique([s.ts for s in self.samples]):
            raise ValueError("samples must be in time order")
        for s in self.samples:
            _position_rules(s.flag, s.reference_fraction, s.distance_m, self.lap_length_m,
                            s.sector)
        return self


def _validate(model: type[_M], doc: dict) -> None:
    try:
        model.model_validate(doc)
    except ValidationError as exc:
        raise SpatialContractError(str(exc)) from exc


def validate_track(doc: dict) -> None:
    _validate(TrackReferenceV1, doc)


def validate_state(doc: dict) -> None:
    _validate(SpatialStateV1, doc)


def validate_trace(doc: dict) -> None:
    _validate(SpatialTraceV1, doc)
