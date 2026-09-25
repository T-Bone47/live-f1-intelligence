/**
 * Contract drift guard: the TypeScript mirror (src/evidence/types.ts) must
 * match the backend's exported JSON Schema (docs/evidence/evidence_v1.schema.json)
 * — every enum member and every field name of the models the UI reads.
 *
 * The Record<keyof T, true> literals are checked by tsc (a missing or extra
 * key is a compile error); the runtime assertion compares them with the
 * schema. Either side changing alone fails this file.
 */

import { describe, expect, it } from "vitest";
import {
  ALIGNMENT_MODES, ATTRIBUTION_STATUSES, CONFIDENCES, LIMITATION_CODES, SEGMENT_KINDS,
  type Accounting, type Alignment, type Braking, type Categorical, type Comparison,
  type LapComparisonEvidenceV1, type Provenance, type Sector, type Segment, type Speed, type Throttle,
} from "../../src/evidence/types";
import { SCHEMA, golden } from "./fixture";

const defs = SCHEMA.$defs as Record<string, { properties?: Record<string, unknown>; enum?: string[] }>;
const props = (name: string) => Object.keys(
  (name === SCHEMA.title ? SCHEMA.properties : defs[name]?.properties) ?? {}).sort();
const keys = (o: object) => Object.keys(o).sort();

const EVIDENCE: Record<keyof LapComparisonEvidenceV1, true> = {
  contract_version: true, evidence_type: true, evidence_id: true, calculation: true, source: true,
  comparison: true, attribution: true, limitations: true, provenance: true,
};
const COMPARISON: Record<keyof Comparison, true> = {
  driver_a: true, driver_b: true, lap_delta_s: true, lap_delta_provenance_class: true,
  engine_delta_last_covered_s: true, last_covered_x: true, sign_convention: true, lap_length: true,
  alignment: true, telemetry_confidence: true,
};
const ALIGNMENT: Record<keyof Alignment, true> = {
  mode: true, misalignment_bound_m: true, within_segment_change_bound_m: true, uncertainty_source: true, anchors: true,
};
const SEGMENT: Record<keyof Segment, true> = {
  segment_id: true, label: true, grid_start_index: true, grid_end_index: true, x_start: true, x_end: true,
  distance_start_m: true, distance_end_m: true, direction: true, inherited_gap_s: true,
  accumulated_change_s: true, delta_end_s: true, uncertainty_s: true, significant: true,
  attribution_status: true, primary_signal: true, supporting_signals: true, onset_order: true,
  accumulation_midpoint_x: true, braking: true, throttle: true, speed: true, gear: true, drs: true,
  phase_accumulation_a: true, phase_accumulation_b: true, dominant_phase_a: true,
  telemetry_confidence: true, association: true, provenance_class: true, provenance: true,
  telemetry_references: true,
};
const BRAKING: Record<keyof Braking, true> = {
  paired: true, applications_a: true, applications_b: true, onset_x_a: true, onset_x_b: true,
  onset_offset_m: true, onset_offset_resolvable: true, release_x_a: true, release_x_b: true,
  release_offset_m: true, release_offset_resolvable: true, peak_pct_a: true, peak_pct_b: true,
  speed_at_onset_a_kph: true, speed_at_onset_b_kph: true, zone_start_x: true, zone_end_x: true,
  delta_before_s: true, delta_during_s: true, delta_after_s: true, band_before_s: true,
  band_during_s: true, band_after_s: true,
};
const THROTTLE: Record<keyof Throttle, true> = {
  full_level_a_pct: true, full_level_b_pct: true, full_modal_a_pct: true, full_modal_b_pct: true,
  lift_x_a: true, lift_x_b: true, lift_offset_m: true, lift_resolvable: true, application_x_a: true,
  application_x_b: true, application_offset_m: true, application_resolvable: true, full_x_a: true,
  full_x_b: true, full_offset_m: true, full_resolvable: true, minimum_a_pct: true, minimum_b_pct: true,
  mean_throttle_difference_pct: true, delta_after_application_s: true,
};
const SPEED: Record<keyof Speed, true> = {
  mean_difference_kph: true, min_difference_kph: true, max_difference_kph: true, min_speed_a_kph: true,
  min_speed_b_kph: true, min_speed_x_a: true, min_speed_x_b: true, min_speed_difference_kph: true,
  min_speed_resolvable: true, end_speed_a_kph: true, end_speed_b_kph: true, divergence_onset_x: true,
  divergence_fraction: true,
};
const CATEGORICAL: Record<keyof Categorical, true> = {
  available: true, difference_fraction: true, runs: true, first_resolvable_x: true, min_a: true,
  min_b: true, values_a: true, values_b: true,
};
const SECTOR: Record<keyof Sector, true> = {
  sector_id: true, sector: true, official_a_s: true, official_b_s: true, official_delta_s: true,
  official_provenance_class: true, engine_change_s: true, engine_minus_official_s: true,
  engine_provenance_class: true, coverage: true, line_x_a: true, line_x_b: true,
  line_misalignment_m: true, segment_ids: true,
};
const ACCOUNTING: Record<keyof Accounting, true> = {
  actual_change_s: true, attributed_change_s: true, unattributed_significant_change_s: true,
  below_significance_change_s: true, unaccounted_s: true, change_by_status: true, no_data_spans: true,
};
const PROVENANCE: Record<keyof Provenance, true> = {
  chain: true, input_digest: true, identity_checks: true, laps: true,
};

describe("evidence_v1 TypeScript mirror vs the backend's exported JSON Schema", () => {
  it.each([
    ["LapComparisonEvidenceV1", EVIDENCE], ["Comparison", COMPARISON], ["Alignment", ALIGNMENT],
    ["Segment", SEGMENT], ["Braking", BRAKING], ["Throttle", THROTTLE], ["Speed", SPEED],
    ["Categorical", CATEGORICAL], ["Sector", SECTOR], ["Accounting", ACCOUNTING], ["Provenance", PROVENANCE],
  ] as const)("%s has exactly the schema's fields", (name, ts) => {
    expect(keys(ts)).toEqual(props(name));
  });

  it.each([
    ["AttributionStatus", ATTRIBUTION_STATUSES], ["SegmentKind", SEGMENT_KINDS],
    ["LimitationCode", LIMITATION_CODES], ["Confidence", CONFIDENCES], ["AlignmentMode", ALIGNMENT_MODES],
  ] as const)("%s enum matches the schema", (name, members) => {
    expect([...members].sort()).toEqual([...(defs[name].enum ?? [])].sort());
  });

  it("the real golden evidence uses only known enum members", () => {
    const ev = golden();
    for (const s of ev.attribution.segments) {
      expect(ATTRIBUTION_STATUSES).toContain(s.attribution_status);
      expect(SEGMENT_KINDS).toContain(s.direction);
      expect(CONFIDENCES).toContain(s.telemetry_confidence);
    }
    for (const l of ev.limitations) expect(LIMITATION_CODES).toContain(l.code);
    expect(ev.contract_version).toBe("evidence_v1");
  });
});
