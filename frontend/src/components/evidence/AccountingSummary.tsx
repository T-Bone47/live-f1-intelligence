/**
 * Accounting of the covered delta change, exactly as the contract states it
 * (§7). The parts are shown, not re-added: the backend validated that they
 * reconcile to 1e-9 before the evidence was released.
 */

import type { EvidenceView } from "../../evidence/viewModel";
import { changeFavours, fmtDelta, fmtX } from "../../evidence/format";
import { STATUS_TEXT } from "../../evidence/vocabulary";
import type { AttributionStatus } from "../../evidence/types";

export function AccountingSummary({ view }: { view: EvidenceView }) {
  const acc = view.evidence.attribution.accounting;
  const byStatus = Object.entries(acc.change_by_status) as [AttributionStatus, number][];
  return (
    <div className="ewb-acc">
      <dl className="ewb-acc-list">
        <div className="is-total">
          <dt>Actual change over covered distance</dt>
          <dd className="ewb-mono">{fmtDelta(acc.actual_change_s)} <span className="ewb-muted">{changeFavours(acc.actual_change_s, view.a, view.b)}</span></dd>
        </div>
        <div><dt>Attributed (one or several inputs differ)</dt><dd className="ewb-mono">{fmtDelta(acc.attributed_change_s)}</dd></div>
        <div><dt>Significant but unattributed</dt><dd className="ewb-mono">{fmtDelta(acc.unattributed_significant_change_s)}</dd></div>
        <div><dt>Below significance</dt><dd className="ewb-mono">{fmtDelta(acc.below_significance_change_s)}</dd></div>
        <div className="is-total"><dt>Unaccounted (actual − attributed)</dt><dd className="ewb-mono">{fmtDelta(acc.unaccounted_s)}</dd></div>
      </dl>
      {byStatus.length > 0 && (
        <p className="ewb-small ewb-muted">
          By evidence state: {byStatus.map(([k, v]) => `${STATUS_TEXT[k]?.label ?? k} ${fmtDelta(v)}`).join(" · ")}
        </p>
      )}
      <p className="ewb-small ewb-muted">
        {acc.no_data_spans.length === 0 ? "No NO_DATA spans."
          : `No-data spans (nothing attributed): ${acc.no_data_spans.map(([a, b]) => `${fmtX(a)}–${b.toFixed(3)}`).join(", ")}.`}
        {" "}Parts reconcile with the actual change; validated by the backend before release.
      </p>
    </div>
  );
}
