/**
 * "Investigate with RaceWise" — the future hand-off seam.
 *
 * Disabled until the integration contract is finalized (VITE_RACEWISE_ENABLED).
 * When enabled it hands the unchanged evidence_v1 to `onHandoff`; this
 * component never calls a reasoning service or shows a simulated answer.
 */

import type { LapComparisonEvidenceV1 } from "../../evidence/types";
import { RACEWISE_ENABLED, buildRaceWiseHandoff, type RaceWiseHandoff } from "../../evidence/racewise";
import { Icon } from "./primitives";

export function InvestigateWithRaceWiseButton({ evidence, focusSegmentIds, onHandoff, enabled = RACEWISE_ENABLED }: {
  evidence: LapComparisonEvidenceV1;
  focusSegmentIds: string[];
  onHandoff?: (h: RaceWiseHandoff) => void;
  enabled?: boolean;
}) {
  const ready = enabled && !!onHandoff;
  return (
    <div className="ewb-racewise">
      <button type="button" className="ewb-btn" disabled={!ready} aria-describedby="ewb-racewise-note"
              onClick={() => onHandoff?.(buildRaceWiseHandoff(evidence, focusSegmentIds))}>
        <Icon name="send" />Investigate with RaceWise
      </button>
      <p id="ewb-racewise-note" className="ewb-small ewb-muted">
        {ready ? `Sends ${evidence.evidence_id} unchanged. RaceWise reasons; this workbench does not.`
          : "Hand-off pending: the RaceWise integration contract is not finalized."}
      </p>
    </div>
  );
}
