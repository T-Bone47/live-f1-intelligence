/**
 * The workbench's fixed vocabulary for contract values.
 *
 * Every label restates what the contract says (docs/RACEWISE_EVIDENCE_CONTRACT.md
 * §5, §10) and nothing stronger: no "because", no "caused", no "better".
 * tests/evidence/vocabulary.test.ts fails if a causal word appears here.
 */

import type {
  AlignmentMode, AttributionStatus, Confidence, LimitationCode, MidpointRelation, SegmentKind,
} from "./types";

export const STATUS_TEXT: Record<AttributionStatus, { label: string; detail: string }> = {
  NOT_SIGNIFICANT: {
    label: "Not significant",
    detail: "The measured change lies within its uncertainty band. There may be observable differences, but not enough to attribute time.",
  },
  SINGLE_CONTROL_INPUT: {
    label: "One control input differs",
    detail: "Significant change; exactly one control-input family differs resolvably. This is a temporal association, not a cause.",
  },
  MULTI_SIGNAL: {
    label: "Several inputs differ",
    detail: "Significant change; several signal families differ resolvably. No primary signal is named.",
  },
  SPEED_ONLY: {
    label: "Only speed differs",
    detail: "Significant change; speed differs beyond alignment error but no control input is resolvable.",
  },
  INSUFFICIENT_EVIDENCE: {
    label: "Insufficient evidence",
    detail: "Significant change, but no signal difference is resolvable (or telemetry confidence is NONE).",
  },
  NO_DATA: {
    label: "No data",
    detail: "No telemetry coverage in this span. No delta exists here and nothing is attributed.",
  },
};

export const DIRECTION_TEXT: Record<SegmentKind, string> = {
  GAINING: "Gaining",
  LOSING: "Losing",
  RECOVERING: "Recovering",
  STABLE: "Stable (within band)",
  NO_DATA: "No data",
};

export const DIRECTION_DETAIL: Record<SegmentKind, string> = {
  GAINING: "A's delta fell by more than the uncertainty band.",
  LOSING: "A's delta rose by more than the uncertainty band.",
  RECOVERING: "A's delta fell by more than the band while A started the segment behind.",
  STABLE: "The change does not exceed the uncertainty band.",
  NO_DATA: "No telemetry coverage.",
};

export const CONFIDENCE_TEXT: Record<Confidence, string> = {
  HIGH: "High", MEDIUM: "Medium", LOW: "Low", NONE: "None",
};

export const ALIGNMENT_TEXT: Record<AlignmentMode, string> = {
  NORMALIZED_DISTANCE: "Normalized distance",
  POSITION_PROJECTED: "Position-projected (unvalidated)",
  CENTERLINE_CALIBRATED: "Centerline-calibrated",
  OTHER: "Other",
};

export const UNCERTAINTY_SOURCE_TEXT: Record<string, string> = {
  SECTOR_LINE_ANCHORS: "measured at the official sector lines",
  PARTIAL_ANCHORS: "measured at one official sector line only",
  PROVISIONAL_DEFAULT: "provisional default (no sector anchors)",
};

export const RELATION_TEXT: Record<MidpointRelation, string> = {
  BEFORE: "before the accumulation midpoint",
  AFTER: "after the accumulation midpoint",
  AT: "at the accumulation midpoint",
  UNDEFINED: "midpoint undefined",
};

const SIGNAL_TEXT: Record<string, string> = {
  brake_onset: "Brake onset",
  brake_release: "Brake release",
  brake_unpaired: "Braking in one lap only",
  throttle_lift: "Throttle lift",
  throttle_application: "Throttle application",
  full_throttle: "Full throttle regained",
  speed: "Speed divergence",
  gear: "Gear difference",
  drs: "DRS code difference",
};

/** Unknown signal names are shown verbatim, never guessed into a label. */
export function signalText(signal: string): string {
  return SIGNAL_TEXT[signal] ?? signal;
}

const FAMILY_TEXT: Record<string, string> = {
  brake: "Brake", throttle: "Throttle", speed: "Speed", gear: "Gear", drs: "DRS",
};

export function familyText(family: string): string {
  return FAMILY_TEXT[family] ?? family;
}

const PHASE_TEXT: Record<string, string> = {
  FULL_THROTTLE: "Full throttle", LIFT: "Lift", BRAKING: "Braking",
  TRANSITION: "Transition", EXIT: "Exit", UNKNOWN: "Unknown",
};

export function phaseText(phase: string): string {
  return PHASE_TEXT[phase] ?? phase;
}

/** Short titles; the backend message is always shown in full beside them. */
export const LIMITATION_TITLE: Record<LimitationCode, string> = {
  ALIGNMENT_NORMALIZED_DISTANCE: "Metres are normalized, not track position",
  ALIGNMENT_POSITION_PROJECTED_UNVALIDATED: "Position projection is unvalidated",
  UNCERTAINTY_DEFAULT_PROVISIONAL: "Uncertainty uses a provisional default",
  UNCERTAINTY_SINGLE_ANCHOR: "Uncertainty rests on one sector line",
  UNCERTAINTY_ANCHORS_LOWER_BOUND: "Uncertainty is a lower bound",
  UNCERTAINTY_WITHIN_SEGMENT_PROVISIONAL: "Within-segment bound is provisional",
  BRAKE_CHANNEL_MISSING: "Brake channel missing",
  THROTTLE_CHANNEL_MISSING: "Throttle channel missing",
  GEAR_CHANNEL_MISSING: "Gear channel missing",
  DRS_CHANNEL_MISSING: "DRS channel missing",
  TELEMETRY_COVERAGE_INCOMPLETE: "Telemetry coverage is incomplete",
  INTRA_SEGMENT_SPLITS_LESS_CERTAIN: "Intra-segment splits are less certain",
  THROTTLE_CALIBRATION_DIFFERS: "Throttle calibration differs per car",
  DRS_SEMANTICS_UNVERIFIED: "DRS meaning is unverified",
  NO_TRACK_GEOMETRY: "No track geometry",
  ASSOCIATION_NOT_CAUSATION: "Association, not causation",
};

/** The consequence for reading the page (contract §10), one line each. */
export const LIMITATION_CONSEQUENCE: Record<LimitationCode, string> = {
  ALIGNMENT_NORMALIZED_DISTANCE: "Every metre on this page is integrated distance ÷ cited lap length.",
  ALIGNMENT_POSITION_PROJECTED_UNVALIDATED: "Position-projected traces have not passed their real-data gate.",
  UNCERTAINTY_DEFAULT_PROVISIONAL: "No official sector anchors: the band is a provisional default.",
  UNCERTAINTY_SINGLE_ANCHOR: "Only one sector line anchors the misalignment bound.",
  UNCERTAINTY_ANCHORS_LOWER_BOUND: "“Significant” means not explained by the measured misalignment.",
  UNCERTAINTY_WITHIN_SEGMENT_PROVISIONAL: "D = E, calibrated on one real pair.",
  BRAKE_CHANNEL_MISSING: "Absent is not “did not brake”.",
  THROTTLE_CHANNEL_MISSING: "No throttle comparison is possible.",
  GEAR_CHANNEL_MISSING: "No gear comparison is possible.",
  DRS_CHANNEL_MISSING: "No DRS comparison is possible.",
  TELEMETRY_COVERAGE_INCOMPLETE: "NO DATA spans exist; nothing is attributed there.",
  INTRA_SEGMENT_SPLITS_LESS_CERTAIN: "Before/during/after and per-phase splits are less certain than totals.",
  THROTTLE_CALIBRATION_DIFFERS: "Mean throttle differences include per-car calibration.",
  DRS_SEMANTICS_UNVERIFIED: "DRS codes are raw; do not read open or closed into them.",
  NO_TRACK_GEOMETRY: "No apex, corner name or corner identity exists.",
  ASSOCIATION_NOT_CAUSATION: "Associations are temporal only.",
};

/** Limitations pinned above the chart: they change how every number reads. */
export const PINNED_LIMITATIONS: readonly LimitationCode[] = [
  "ALIGNMENT_NORMALIZED_DISTANCE",
  "UNCERTAINTY_ANCHORS_LOWER_BOUND",
  "ASSOCIATION_NOT_CAUSATION",
  "UNCERTAINTY_DEFAULT_PROVISIONAL",
  "ALIGNMENT_POSITION_PROJECTED_UNVALIDATED",
];

export const CLASS_TEXT: Record<"B" | "C" | "F", { short: string; long: string }> = {
  B: { short: "Official", long: "Class B — historical observation (official timing)" },
  C: { short: "Derived", long: "Class C — deterministic engine derivation" },
  F: { short: "Unavailable", long: "Class F — unavailable" },
};
