"""evidence_v1 - the versioned, machine-readable evidence contract (Phase 10.5).

Live F1 Intelligence MEASURES; consumers (RaceWise, the 10.6 UI) REASON.
This schema carries Phase 10.4 results verbatim - it never recomputes,
rounds, strengthens or reinterprets them - plus the provenance a consumer
needs to trace every value back to identity-guarded provider rows.

Validation is strict and FAILS CLOSED: unknown fields, wrong types
("1.5" for a number, 1.0 for an integer), NaN/Infinity, inconsistent
significance labels, broken accounting, unstable identifiers or mismatched
identities all reject the payload. docs/RACEWISE_EVIDENCE_CONTRACT.md is
the human-readable form; docs/evidence/evidence_v1.schema.json is exported
from these models.

Evidence classes reuse this project's ProvenanceClass letters (A-F):
B = historical observation (official timing), C = deterministic derivation
(engine values), F = unavailable.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis.attribution import AlignmentMode, AttributionStatus, LimitationCode
from app.analysis.attribution_signals import Phase
from app.analysis.common.models import Confidence
from app.analysis.delta_analysis import SIGN_CONVENTION, SegmentKind

CONTRACT_VERSION = "evidence_v1"
SUPPORTED_CONTRACTS = (CONTRACT_VERSION,)
ASSOCIATION = "TEMPORAL_ASSOCIATION"
RECONCILE_TOL_S = 1e-9  # float summation only; the values themselves are 10.4's


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


# ------------------------------------------------------------- identifiers


def evidence_id_for(*, contract_version: str, attribution_version: str,
                    lap_distance_version: str, session_id: str, driver_a: int, lap_a: int,
                    driver_b: int, lap_b: int, lap_length_m: float, lap_length_source: str,
                    input_digest: str) -> str:
    """Content-addressed: same inputs + same calculation versions -> same id.
    A changed algorithm version or changed input rows -> a different id."""
    key = json.dumps([contract_version, attribution_version, lap_distance_version, session_id,
                      driver_a, lap_a, driver_b, lap_b, repr(float(lap_length_m)),
                      lap_length_source, input_digest], separators=(",", ":"))
    return "ev1_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def segment_id_for(evidence_id: str, start_index: int, end_index: int) -> str:
    return f"{evidence_id}:g{start_index}-{end_index}"


def sector_id_for(evidence_id: str, sector: int) -> str:
    return f"{evidence_id}:S{sector}"


# ------------------------------------------------------------------ blocks


class Calculation(_Model):
    contract_version: Literal["evidence_v1"]
    evidence_builder_version: str = Field(min_length=1)
    attribution_version: str = Field(min_length=1)     # app.analysis.attribution.CALC_VERSION
    lap_distance_version: str = Field(min_length=1)    # app.analysis.lap_distance.CALC_VERSION


class Source(_Model):
    provider: str | None
    session_id: str = Field(min_length=1)
    session_type: str | None
    season: int | None
    event: str | None          # meeting name - null when not in the stored/fixture metadata
    circuit: str | None


class Channels(_Model):
    brake: bool
    throttle: bool
    gear: bool
    drs: bool


class TelemetryCoverage(_Model):
    sample_count: int = Field(ge=0)
    x_first: float | None
    x_last: float | None
    integrated_distance_m: float | None
    complete: bool                 # 10.1B: telemetry spans the lap's official window
    confidence: Confidence         # 10.1B trace confidence (telemetry integrity)
    channels: Channels


class DriverLap(_Model):
    driver_number: int = Field(ge=1, le=99)
    lap_number: int = Field(ge=1)
    lap_duration_s: float | None
    started_at: str
    telemetry: TelemetryCoverage


class LapLength(_Model):
    m: float = Field(gt=0)
    source: str = Field(min_length=1, max_length=300)


class Anchor(_Model):
    line: Literal["S1", "S2"]
    distance_a_m: float
    distance_b_m: float
    misalignment_m: float


class Alignment(_Model):
    mode: AlignmentMode
    misalignment_bound_m: float = Field(ge=0)            # E
    within_segment_change_bound_m: float = Field(ge=0)   # D
    uncertainty_source: Literal["SECTOR_LINE_ANCHORS", "PARTIAL_ANCHORS", "PROVISIONAL_DEFAULT"]
    anchors: list[Anchor]


class Comparison(_Model):
    driver_a: DriverLap
    driver_b: DriverLap
    lap_delta_s: float | None                     # official A - B (class B)
    lap_delta_provenance_class: Literal["B", "F"]
    engine_delta_last_covered_s: float | None     # 10.4 (class C)
    last_covered_x: float | None
    sign_convention: Literal[SIGN_CONVENTION]  # type: ignore[valid-type]
    lap_length: LapLength
    alignment: Alignment
    telemetry_confidence: Confidence              # 10.1C comparison confidence


class SignalOnset(_Model):
    signal: str
    family: Literal["brake", "throttle", "speed", "gear", "drs"]
    x: float
    distance_m: float
    relation_to_midpoint: Literal["BEFORE", "AFTER", "AT", "UNDEFINED"]
    association: Literal["TEMPORAL_ASSOCIATION"]


class Braking(_Model):
    paired: bool
    applications_a: int
    applications_b: int
    onset_x_a: float | None
    onset_x_b: float | None
    onset_offset_m: float | None
    onset_offset_resolvable: bool
    release_x_a: float | None
    release_x_b: float | None
    release_offset_m: float | None
    release_offset_resolvable: bool
    peak_pct_a: float | None
    peak_pct_b: float | None
    speed_at_onset_a_kph: float | None
    speed_at_onset_b_kph: float | None
    zone_start_x: float
    zone_end_x: float
    delta_before_s: float
    delta_during_s: float
    delta_after_s: float
    band_before_s: float | None
    band_during_s: float | None
    band_after_s: float | None


class Throttle(_Model):
    full_level_a_pct: float | None
    full_level_b_pct: float | None
    full_modal_a_pct: float | None
    full_modal_b_pct: float | None
    lift_x_a: float | None
    lift_x_b: float | None
    lift_offset_m: float | None
    lift_resolvable: bool
    application_x_a: float | None
    application_x_b: float | None
    application_offset_m: float | None
    application_resolvable: bool
    full_x_a: float | None
    full_x_b: float | None
    full_offset_m: float | None
    full_resolvable: bool
    minimum_a_pct: float | None
    minimum_b_pct: float | None
    mean_throttle_difference_pct: float | None
    delta_after_application_s: float | None


class Speed(_Model):
    mean_difference_kph: float | None
    min_difference_kph: float | None
    max_difference_kph: float | None
    min_speed_a_kph: float | None
    min_speed_b_kph: float | None
    min_speed_x_a: float | None
    min_speed_x_b: float | None
    min_speed_difference_kph: float | None
    min_speed_resolvable: bool
    end_speed_a_kph: float | None
    end_speed_b_kph: float | None
    divergence_onset_x: float | None
    divergence_fraction: float | None


class DifferenceRun(_Model):
    x_start: float
    x_end: float
    length_m: float
    resolvable: bool


class Categorical(_Model):
    available: bool
    difference_fraction: float | None = Field(ge=0, le=1)
    runs: list[DifferenceRun]
    first_resolvable_x: float | None
    min_a: int | None
    min_b: int | None
    values_a: list[int]
    values_b: list[int]


class TelemetryReference(_Model):
    """Drill-down pointer to the EXISTING telemetry route - never the data itself."""
    driver_number: int
    lap_number: int
    route: str
    start: str
    end: str


class SegmentProvenance(_Model):
    delta_source: Literal["10.2 DeltaSample.delta_t_s"]
    grid_indices: tuple[int, int]
    sample_indices_a: tuple[int, int]
    sample_indices_b: tuple[int, int]
    ts_range_a: tuple[str, str] | None
    ts_range_b: tuple[str, str] | None


_PHASES = {p.value for p in Phase}


class Segment(_Model):
    segment_id: str
    label: str
    grid_start_index: int
    grid_end_index: int
    x_start: float
    x_end: float
    distance_start_m: float
    distance_end_m: float
    direction: SegmentKind
    inherited_gap_s: float | None
    accumulated_change_s: float | None
    delta_end_s: float | None
    uncertainty_s: float | None
    significant: bool
    attribution_status: AttributionStatus
    primary_signal: str | None
    supporting_signals: list[str]
    onset_order: list[SignalOnset]
    accumulation_midpoint_x: float | None
    braking: Braking | None
    throttle: Throttle | None
    speed: Speed | None
    gear: Categorical
    drs: Categorical
    phase_accumulation_a: dict[str, float]
    phase_accumulation_b: dict[str, float]
    dominant_phase_a: str | None
    telemetry_confidence: Confidence
    association: Literal["TEMPORAL_ASSOCIATION"]
    provenance_class: Literal["C", "F"]
    provenance: SegmentProvenance
    telemetry_references: list[TelemetryReference]

    @model_validator(mode="after")
    def _significance_is_consistent(self) -> Segment:
        if not (set(self.phase_accumulation_a) | set(self.phase_accumulation_b)) <= _PHASES:
            raise ValueError("unknown phase in phase_accumulation")
        if self.direction is SegmentKind.NO_DATA:
            if (self.attribution_status is not AttributionStatus.NO_DATA
                    or self.accumulated_change_s is not None or self.significant
                    or self.provenance_class != "F"):
                raise ValueError(f"{self.label}: NO_DATA segment carries data")
            return self
        if self.accumulated_change_s is None or self.uncertainty_s is None:
            if self.significant:
                raise ValueError(f"{self.label}: significant without change/uncertainty")
        elif self.significant != (abs(self.accumulated_change_s) > self.uncertainty_s):
            raise ValueError(f"{self.label}: 'significant' disagrees with |change| > uncertainty")
        if not self.significant:
            if (self.direction is not SegmentKind.STABLE or self.primary_signal is not None
                    or self.supporting_signals
                    or self.attribution_status is not AttributionStatus.NOT_SIGNIFICANT):
                raise ValueError(f"{self.label}: non-significant segment carries attribution")
        else:
            change = self.accumulated_change_s
            if self.direction is SegmentKind.LOSING and not change > 0:
                raise ValueError(f"{self.label}: LOSING with change <= 0")
            if self.direction in (SegmentKind.GAINING, SegmentKind.RECOVERING) and not change < 0:
                raise ValueError(f"{self.label}: GAINING/RECOVERING with change >= 0")
            if self.direction is SegmentKind.RECOVERING and not (self.inherited_gap_s or 0) > 0:
                raise ValueError(f"{self.label}: RECOVERING without an inherited deficit")
            if self.attribution_status in (AttributionStatus.NOT_SIGNIFICANT,
                                           AttributionStatus.NO_DATA):
                raise ValueError(f"{self.label}: significant segment with status "
                                 f"{self.attribution_status.value}")
        if self.provenance.grid_indices != (self.grid_start_index, self.grid_end_index):
            raise ValueError(f"{self.label}: provenance grid indices disagree")
        return self


class Accounting(_Model):
    actual_change_s: float
    attributed_change_s: float
    unattributed_significant_change_s: float
    below_significance_change_s: float
    unaccounted_s: float
    change_by_status: dict[str, float]
    no_data_spans: list[tuple[float, float]]

    @model_validator(mode="after")
    def _reconciles(self) -> Accounting:
        parts = (self.attributed_change_s + self.unattributed_significant_change_s
                 + self.below_significance_change_s)
        if abs(parts - self.actual_change_s) > RECONCILE_TOL_S:
            raise ValueError("accounting does not reconcile with the actual change")
        if abs(self.actual_change_s - self.attributed_change_s - self.unaccounted_s) > 1e-12:
            raise ValueError("unaccounted_s != actual - attributed")
        if not set(self.change_by_status) <= {s.value for s in AttributionStatus}:
            raise ValueError("unknown status in change_by_status")
        return self


class Sector(_Model):
    sector_id: str
    sector: Literal[1, 2, 3]
    official_a_s: float | None
    official_b_s: float | None
    official_delta_s: float | None
    official_provenance_class: Literal["B", "F"]
    engine_change_s: float | None
    engine_minus_official_s: float | None
    engine_provenance_class: Literal["C", "F"]
    coverage: Literal["COVERED", "NOT_COVERED"]
    line_x_a: float | None
    line_x_b: float | None
    line_misalignment_m: float | None
    segment_ids: list[str]


class Attribution(_Model):
    segments: list[Segment]
    accounting: Accounting
    sectors: list[Sector]


class LimitationItem(_Model):
    code: LimitationCode
    message: str = Field(min_length=1)


class LapProvenance(_Model):
    driver_number: int
    lap_number: int
    session_id: str
    lap_started_at: str
    telemetry_first_ts: str | None
    telemetry_last_ts: str | None
    sample_count: int


class Provenance(_Model):
    chain: list[str] = Field(min_length=1)
    input_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    identity_checks: list[str]
    laps: tuple[LapProvenance, LapProvenance]


class LapComparisonEvidenceV1(_Model):
    contract_version: Literal["evidence_v1"]
    evidence_type: Literal["lap_comparison"]
    evidence_id: str
    calculation: Calculation
    source: Source
    comparison: Comparison
    attribution: Attribution
    limitations: list[LimitationItem] = Field(min_length=1)
    provenance: Provenance

    @model_validator(mode="after")
    def _integrity(self) -> LapComparisonEvidenceV1:
        cmp, calc = self.comparison, self.calculation
        a, b = cmp.driver_a, cmp.driver_b
        if calc.contract_version != self.contract_version:
            raise ValueError("calculation.contract_version != contract_version")
        expected = evidence_id_for(
            contract_version=self.contract_version,
            attribution_version=calc.attribution_version,
            lap_distance_version=calc.lap_distance_version, session_id=self.source.session_id,
            driver_a=a.driver_number, lap_a=a.lap_number, driver_b=b.driver_number,
            lap_b=b.lap_number, lap_length_m=cmp.lap_length.m,
            lap_length_source=cmp.lap_length.source, input_digest=self.provenance.input_digest)
        if self.evidence_id != expected:
            raise ValueError("evidence_id does not match its content key (tampered or unstable)")
        segs = self.attribution.segments
        ids = [s.segment_id for s in segs]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate segment_id")
        for s in segs:
            if s.segment_id != segment_id_for(self.evidence_id, s.grid_start_index,
                                              s.grid_end_index):
                raise ValueError(f"{s.label}: segment_id is not the stable id")
            for ref in s.telemetry_references:
                if (ref.driver_number, ref.lap_number) not in (
                        (a.driver_number, a.lap_number), (b.driver_number, b.lap_number)):
                    raise ValueError(f"{s.label}: telemetry reference to another driver/lap")
        for prev, nxt in itertools.pairwise(segs):
            if nxt.grid_start_index != prev.grid_end_index or nxt.x_start < prev.x_start:
                raise ValueError("segments are not contiguous and ordered")
        changes = [s.accumulated_change_s for s in segs if s.accumulated_change_s is not None]
        if abs(sum(changes) - self.attribution.accounting.actual_change_s) > RECONCILE_TOL_S:
            raise ValueError("segment changes do not sum to the accounted actual change")
        for sec in self.attribution.sectors:
            if sec.sector_id != sector_id_for(self.evidence_id, sec.sector):
                raise ValueError(f"sector {sec.sector}: sector_id is not the stable id")
            if not set(sec.segment_ids) <= set(ids):
                raise ValueError(f"sector {sec.sector}: references unknown segments")
            if (sec.coverage == "COVERED") != (sec.engine_change_s is not None):
                raise ValueError(f"sector {sec.sector}: coverage disagrees with engine value")
        pa, pb = self.provenance.laps
        if ((pa.driver_number, pa.lap_number), (pb.driver_number, pb.lap_number)) != (
                (a.driver_number, a.lap_number), (b.driver_number, b.lap_number)):
            raise ValueError("provenance laps disagree with the comparison")
        if {pa.session_id, pb.session_id} != {self.source.session_id}:
            raise ValueError("provenance session disagrees with source.session_id")
        return self


def json_schema() -> dict:
    return LapComparisonEvidenceV1.model_json_schema()
