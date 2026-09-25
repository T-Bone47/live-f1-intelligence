/**
 * Loading, error and empty states. Errors keep the backend's own message and
 * say what to do next; nothing is substituted for missing evidence.
 */

import type { EvidenceError } from "../../evidence/api";
import { Icon } from "./primitives";

const ERROR_TEXT: Record<EvidenceError["kind"], { title: string; next: string }> = {
  invalid: { title: "Comparison refused (422)", next: "Check the drivers, laps and lap-length citation. A lap needs a duration and stored telemetry." },
  not_found: { title: "Not found (404)", next: "The session, driver or lap is not stored. Check the ids, or seed the data first." },
  withheld: { title: "Evidence withheld (500)", next: "The backend built evidence that failed evidence_v1 validation, so it was not released. Nothing is shown in its place." },
  rate_limited: { title: "Rate limited (429)", next: "Wait a moment, then retry." },
  unavailable: { title: "Evidence API unavailable", next: "The backend could not be reached. Start it (scripts/serve_evidence_dev.py) and retry." },
  unsupported: { title: "Unsupported response", next: "The response was not evidence_v1, so nothing is rendered." },
  unexpected: { title: "Unexpected error", next: "Retry; if it persists, check the backend log." },
};

export function EvidenceErrorState({ error, onRetry }: { error: EvidenceError; onRetry: () => void }) {
  const t = ERROR_TEXT[error.kind];
  return (
    <div className="ewb-state-box is-error" role="alert">
      <Icon name="alert" size={18} />
      <div>
        <p className="ewb-state-title">{t.title}</p>
        <p className="ewb-state-msg"><code>{error.message}</code></p>
        <p className="ewb-state-next">{t.next}</p>
        {error.kind !== "invalid" && error.kind !== "not_found" && (
          <button type="button" className="ewb-btn" onClick={onRetry}><Icon name="refresh" />Retry</button>
        )}
      </div>
    </div>
  );
}

export function EvidenceEmptyState() {
  return (
    <div className="ewb-state-box is-empty" role="status">
      <Icon name="info" size={18} />
      <div>
        <p className="ewb-state-title">No comparison loaded</p>
        <p className="ewb-state-next">
          Choose a session, two drivers and their laps, and cite the lap length. The workbench then shows where
          the delta changed, how certain each change is, and which signals differed — as evidence, not conclusions.
        </p>
      </div>
    </div>
  );
}

export function EvidenceLoadingState() {
  return (
    <div className="ewb-skeleton" role="status" aria-busy="true" aria-label="Loading evidence">
      <div className="ewb-skel ewb-skel-summary" />
      <div className="ewb-skel ewb-skel-chart" />
      <div className="ewb-skel ewb-skel-rows" />
      <span className="ewb-sr">Loading evidence…</span>
    </div>
  );
}
