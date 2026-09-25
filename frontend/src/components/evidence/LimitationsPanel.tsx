/**
 * Limitations: always visible, never a tooltip. The pinned strip sits above
 * the chart; the full list shows every code with the backend's own message.
 */

import type { EvidenceView } from "../../evidence/viewModel";
import { LIMITATION_CONSEQUENCE, LIMITATION_TITLE } from "../../evidence/vocabulary";
import { Icon } from "./primitives";

export function CaveatStrip({ view, onShowAll }: { view: EvidenceView; onShowAll: () => void }) {
  if (view.pinned.length === 0) return null;
  return (
    <aside className="ewb-caveats" aria-label="Key limitations">
      <Icon name="alert" />
      <ul>
        {view.pinned.map((l) => (
          <li key={l.code}><strong>{LIMITATION_TITLE[l.code]}.</strong> {LIMITATION_CONSEQUENCE[l.code]}</li>
        ))}
      </ul>
      <button type="button" className="ewb-link" onClick={onShowAll}>
        All {view.evidence.limitations.length} limitations
      </button>
    </aside>
  );
}

export function LimitationsPanel({ view }: { view: EvidenceView }) {
  return (
    <ul className="ewb-limits">
      {view.evidence.limitations.map((l) => (
        <li key={l.code} className="ewb-limit">
          <p className="ewb-limit-title">{LIMITATION_TITLE[l.code] ?? l.code}</p>
          <p className="ewb-limit-consequence">{LIMITATION_CONSEQUENCE[l.code] ?? ""}</p>
          <p className="ewb-limit-msg"><code>{l.code}</code> {l.message}</p>
        </li>
      ))}
    </ul>
  );
}
