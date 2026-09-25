/**
 * evidence_v1 — TypeScript mirror of backend/app/evidence/schema.py.
 *
 * Field names, nullability and enum members are copied from the pydantic
 * models (and docs/evidence/evidence_v1.schema.json). This is the ONLY place
 * the contract is described on the frontend; components import from here.
 * tests/evidence/contract.test.ts checks the real golden file and the
 * exported JSON Schema against these enums so a backend change cannot drift
 * silently.
 */

export const CONTRACT_VERSION = "evidence_v1" as const;

export const SIGN_CONVENTION =
  "delta_t = elapsed_A - elapsed_B; negative means A is ahead" as const;

export type Confidence = "HIGH" | "MEDIUM" | "LOW" | "NONE";
export type AlignmentMode =
  | "NORMALIZED_DISTANCE" | "POSITION_PROJECTED" | "CENTERLINE_CALIBRATED" | "OTHER";
export type SegmentKind = "GAINING" | "LOSING" | "RECOVERING" | "STABLE" | "NO_DATA";
export type AttributionStatus =
  | "SINGLE_CONTROL_INPUT" | "MULTI_SIGNAL" | "SPEED_ONLY"
  | "INSUFFICIENT_EVIDENCE" | "NOT_SIGNIFICANT" | "NO_DATA";
export type LimitationCode =
  | "ALIGNMENT_NORMALIZED_DISTANCE" | "ALIGNMENT_POSITION_PROJECTED_UNVALIDATED"
  | "UNCERTAINTY_DEFAULT_PROVISIONAL" | "UNCERTAINTY_SINGLE_ANCHOR"
  | "UNCERTAINTY_ANCHORS_LOWER_BOUND" | "UNCERTAINTY_WITHIN_SEGMENT_PROVISIONAL"
  | "BRAKE_CHANNEL_MISSING" | "THROTTLE_CHANNEL_MISSING" | "GEAR_CHANNEL_MISSING"
  | "DRS_CHANNEL_MISSING" | "TELEMETRY_COVERAGE_INCOMPLETE"
  | "INTRA_SEGMENT_SPLITS_LESS_CERTAIN" | "THROTTLE_CALIBRATION_DIFFERS"
  | "DRS_SEMANTICS_UNVERIFIED" | "NO_TRACK_GEOMETRY" | "ASSOCIATION_NOT_CAUSATION";
export type SignalFamily = "brake" | "throttle" | "speed" | "gear" | "drs";
export type MidpointRelation = "BEFORE" | "AFTER" | "AT" | "UNDEFINED";
export type Association = "TEMPORAL_ASSOCIATION";

export const CONFIDENCES: readonly Confidence[] = ["HIGH", "MEDIUM", "LOW", "NONE"];
export const ALIGNMENT_MODES: readonly AlignmentMode[] =
  ["NORMALIZED_DISTANCE", "POSITION_PROJECTED", "CENTERLINE_CALIBRATED", "OTHER"];
export const ATTRIBUTION_STATUSES: readonly AttributionStatus[] = [
  "SINGLE_CONTROL_INPUT", "MULTI_SIGNAL", "SPEED_ONLY",
  "INSUFFICIENT_EVIDENCE", "NOT_SIGNIFICANT", "NO_DATA",
];
export const SEGMENT_KINDS: readonly SegmentKind[] =
  ["GAINING", "LOSING", "RECOVERING", "STABLE", "NO_DATA"];
export const LIMITATION_CODES: readonly LimitationCode[] = [
  "ALIGNMENT_NORMALIZED_DISTANCE", "ALIGNMENT_POSITION_PROJECTED_UNVALIDATED",
  "UNCERTAINTY_DEFAULT_PROVISIONAL", "UNCERTAINTY_SINGLE_ANCHOR",
  "UNCERTAINTY_ANCHORS_LOWER_BOUND", "UNCERTAINTY_WITHIN_SEGMENT_PROVISIONAL",
  "BRAKE_CHANNEL_MISSING", "THROTTLE_CHANNEL_MISSING", "GEAR_CHANNEL_MISSING",
  "DRS_CHANNEL_MISSING", "TELEMETRY_COVERAGE_INCOMPLETE",
  "INTRA_SEGMENT_SPLITS_LESS_CERTAIN", "THROTTLE_CALIBRATION_DIFFERS",
  "DRS_SEMANTICS_UNVERIFIED", "NO_TRACK_GEOMETRY", "ASSOCIATION_NOT_CAUSATION",
];

export interface Calculation {
  contract_version: typeof CONTRACT_VERSION;
  evidence_builder_version: string;
  attribution_version: string;
  lap_distance_version: string;
}

export interface Source {
  provider: string | null;
  session_id: string;
  session_type: string | null;
  season: number | null;
  event: string | null;
  circuit: string | null;
}

export interface Channels { brake: boolean; throttle: boolean; gear: boolean; drs: boolean }

export interface TelemetryCoverage {
  sample_count: number;
  x_first: number | null;
  x_last: number | null;
  integrated_distance_m: number | null;
  complete: boolean;
  confidence: Confidence;
  channels: Channels;
}

export interface DriverLap {
  driver_number: number;
  lap_number: number;
  lap_duration_s: number | null;
  started_at: string;
  telemetry: TelemetryCoverage;
}

export interface LapLength { m: number; source: string }

export interface Anchor {
  line: "S1" | "S2";
  distance_a_m: number;
  distance_b_m: number;
  misalignment_m: number;
}

export interface Alignment {
  mode: AlignmentMode;
  misalignment_bound_m: number;
  within_segment_change_bound_m: number;
  uncertainty_source: "SECTOR_LINE_ANCHORS" | "PARTIAL_ANCHORS" | "PROVISIONAL_DEFAULT";
  anchors: Anchor[];
}

export interface Comparison {
  driver_a: DriverLap;
  driver_b: DriverLap;
  lap_delta_s: number | null;
  lap_delta_provenance_class: "B" | "F";
  engine_delta_last_covered_s: number | null;
  last_covered_x: number | null;
  sign_convention: typeof SIGN_CONVENTION;
  lap_length: LapLength;
  alignment: Alignment;
  telemetry_confidence: Confidence;
}

export interface SignalOnset {
  signal: string;
  family: SignalFamily;
  x: number;
  distance_m: number;
  relation_to_midpoint: MidpointRelation;
  association: Association;
}

export interface Braking {
  paired: boolean;
  applications_a: number;
  applications_b: number;
  onset_x_a: number | null;
  onset_x_b: number | null;
  onset_offset_m: number | null;
  onset_offset_resolvable: boolean;
  release_x_a: number | null;
  release_x_b: number | null;
  release_offset_m: number | null;
  release_offset_resolvable: boolean;
  peak_pct_a: number | null;
  peak_pct_b: number | null;
  speed_at_onset_a_kph: number | null;
  speed_at_onset_b_kph: number | null;
  zone_start_x: number;
  zone_end_x: number;
  delta_before_s: number;
  delta_during_s: number;
  delta_after_s: number;
  band_before_s: number | null;
  band_during_s: number | null;
  band_after_s: number | null;
}

export interface Throttle {
  full_level_a_pct: number | null;
  full_level_b_pct: number | null;
  full_modal_a_pct: number | null;
  full_modal_b_pct: number | null;
  lift_x_a: number | null;
  lift_x_b: number | null;
  lift_offset_m: number | null;
  lift_resolvable: boolean;
  application_x_a: number | null;
  application_x_b: number | null;
  application_offset_m: number | null;
  application_resolvable: boolean;
  full_x_a: number | null;
  full_x_b: number | null;
  full_offset_m: number | null;
  full_resolvable: boolean;
  minimum_a_pct: number | null;
  minimum_b_pct: number | null;
  mean_throttle_difference_pct: number | null;
  delta_after_application_s: number | null;
}

export interface Speed {
  mean_difference_kph: number | null;
  min_difference_kph: number | null;
  max_difference_kph: number | null;
  min_speed_a_kph: number | null;
  min_speed_b_kph: number | null;
  min_speed_x_a: number | null;
  min_speed_x_b: number | null;
  min_speed_difference_kph: number | null;
  min_speed_resolvable: boolean;
  end_speed_a_kph: number | null;
  end_speed_b_kph: number | null;
  divergence_onset_x: number | null;
  divergence_fraction: number | null;
}

export interface DifferenceRun { x_start: number; x_end: number; length_m: number; resolvable: boolean }

export interface Categorical {
  available: boolean;
  difference_fraction: number | null;
  runs: DifferenceRun[];
  first_resolvable_x: number | null;
  min_a: number | null;
  min_b: number | null;
  values_a: number[];
  values_b: number[];
}

/** Drill-down pointer to the EXISTING telemetry route — never the data itself. */
export interface TelemetryReference {
  driver_number: number;
  lap_number: number;
  route: string;
  start: string;
  end: string;
}

export interface SegmentProvenance {
  delta_source: "10.2 DeltaSample.delta_t_s";
  grid_indices: [number, number];
  sample_indices_a: [number, number];
  sample_indices_b: [number, number];
  ts_range_a: [string, string] | null;
  ts_range_b: [string, string] | null;
}

export interface Segment {
  segment_id: string;
  label: string;
  grid_start_index: number;
  grid_end_index: number;
  x_start: number;
  x_end: number;
  distance_start_m: number;
  distance_end_m: number;
  direction: SegmentKind;
  inherited_gap_s: number | null;
  accumulated_change_s: number | null;
  delta_end_s: number | null;
  uncertainty_s: number | null;
  significant: boolean;
  attribution_status: AttributionStatus;
  primary_signal: string | null;
  supporting_signals: string[];
  onset_order: SignalOnset[];
  accumulation_midpoint_x: number | null;
  braking: Braking | null;
  throttle: Throttle | null;
  speed: Speed | null;
  gear: Categorical;
  drs: Categorical;
  phase_accumulation_a: Record<string, number>;
  phase_accumulation_b: Record<string, number>;
  dominant_phase_a: string | null;
  telemetry_confidence: Confidence;
  association: Association;
  provenance_class: "C" | "F";
  provenance: SegmentProvenance;
  telemetry_references: TelemetryReference[];
}

export interface Accounting {
  actual_change_s: number;
  attributed_change_s: number;
  unattributed_significant_change_s: number;
  below_significance_change_s: number;
  unaccounted_s: number;
  change_by_status: Partial<Record<AttributionStatus, number>>;
  no_data_spans: [number, number][];
}

export interface Sector {
  sector_id: string;
  sector: 1 | 2 | 3;
  official_a_s: number | null;
  official_b_s: number | null;
  official_delta_s: number | null;
  official_provenance_class: "B" | "F";
  engine_change_s: number | null;
  engine_minus_official_s: number | null;
  engine_provenance_class: "C" | "F";
  coverage: "COVERED" | "NOT_COVERED";
  line_x_a: number | null;
  line_x_b: number | null;
  line_misalignment_m: number | null;
  segment_ids: string[];
}

export interface Attribution { segments: Segment[]; accounting: Accounting; sectors: Sector[] }

export interface LimitationItem { code: LimitationCode; message: string }

export interface LapProvenance {
  driver_number: number;
  lap_number: number;
  session_id: string;
  lap_started_at: string;
  telemetry_first_ts: string | null;
  telemetry_last_ts: string | null;
  sample_count: number;
}

export interface Provenance {
  chain: string[];
  input_digest: string;
  identity_checks: string[];
  laps: [LapProvenance, LapProvenance];
}

export interface LapComparisonEvidenceV1 {
  contract_version: typeof CONTRACT_VERSION;
  evidence_type: "lap_comparison";
  evidence_id: string;
  calculation: Calculation;
  source: Source;
  comparison: Comparison;
  attribution: Attribution;
  limitations: LimitationItem[];
  provenance: Provenance;
}
