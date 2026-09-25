/**
 * RaceWise integration seam (future).
 *
 * LFI is the evidence engine; RaceWise reasons. The hand-off carries the
 * evidence_v1 object unchanged, keyed by evidence_id. No network call exists
 * here and no response is simulated: until the integration contract is
 * finalized the seam is disabled (VITE_RACEWISE_ENABLED !== "true").
 */

import type { LapComparisonEvidenceV1 } from "./types";

export const RACEWISE_ENABLED = import.meta.env.VITE_RACEWISE_ENABLED === "true";

export interface RaceWiseHandoff {
  contract_version: LapComparisonEvidenceV1["contract_version"];
  evidence_type: LapComparisonEvidenceV1["evidence_type"];
  evidence_id: string;
  /** Optional focus: segment_ids the user had selected. References only. */
  focus_segment_ids: string[];
  evidence: LapComparisonEvidenceV1;
}

export function buildRaceWiseHandoff(
  evidence: LapComparisonEvidenceV1, focusSegmentIds: string[] = [],
): RaceWiseHandoff {
  return {
    contract_version: evidence.contract_version,
    evidence_type: evidence.evidence_type,
    evidence_id: evidence.evidence_id,
    focus_segment_ids: focusSegmentIds,
    evidence,
  };
}
