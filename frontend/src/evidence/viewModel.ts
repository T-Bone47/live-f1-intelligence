/**
 * UI-only view model over evidence_v1: lookups and flags for rendering.
 *
 * Everything here is indexing or selection of values the evidence already
 * carries. Nothing is computed that the contract does not state (no delta,
 * no significance, no boundary, no accounting).
 */

import type { LapComparisonEvidenceV1, LimitationCode, Segment, Sector } from "./types";
import { PINNED_LIMITATIONS } from "./vocabulary";

export interface EvidenceView {
  evidence: LapComparisonEvidenceV1;
  a: number;
  b: number;
  /** ALIGNMENT_NORMALIZED_DISTANCE present: every metre label says "norm." */
  normalized: boolean;
  segments: Segment[];
  byLabel: Map<string, Segment>;
  byId: Map<string, Segment>;
  sectorsBySegment: Map<string, Sector[]>;
  pinned: { code: LimitationCode; message: string }[];
  hasLimitation: (code: LimitationCode) => boolean;
}

export function buildView(evidence: LapComparisonEvidenceV1): EvidenceView {
  const segments = evidence.attribution.segments;
  const codes = new Set(evidence.limitations.map((l) => l.code));
  const sectorsBySegment = new Map<string, Sector[]>();
  for (const sec of evidence.attribution.sectors) {
    for (const id of sec.segment_ids) {
      sectorsBySegment.set(id, [...(sectorsBySegment.get(id) ?? []), sec]);
    }
  }
  return {
    evidence,
    a: evidence.comparison.driver_a.driver_number,
    b: evidence.comparison.driver_b.driver_number,
    normalized: codes.has("ALIGNMENT_NORMALIZED_DISTANCE"),
    segments,
    byLabel: new Map(segments.map((s) => [s.label, s])),
    byId: new Map(segments.map((s) => [s.segment_id, s])),
    sectorsBySegment,
    pinned: PINNED_LIMITATIONS
      .map((code) => evidence.limitations.find((l) => l.code === code))
      .filter((l): l is { code: LimitationCode; message: string } => !!l),
    hasLimitation: (code) => codes.has(code),
  };
}

/** Neighbouring label in lap order, clamped at the ends (keyboard navigation). */
export function stepLabel(segments: Segment[], current: string | null, step: number): string | null {
  if (segments.length === 0) return null;
  const i = current == null ? -1 : segments.findIndex((s) => s.label === current);
  if (i < 0) return step >= 0 ? segments[0].label : segments[segments.length - 1].label;
  return segments[Math.max(0, Math.min(segments.length - 1, i + step))].label;
}
