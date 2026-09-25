/**
 * Engineering provenance: identity, versions, alignment anchors and the
 * lineage chain from evidence_v1 back to identity-guarded provider rows.
 */

import { useState } from "react";
import type { EvidenceView } from "../../evidence/viewModel";
import { fmtClock, fmtMetres } from "../../evidence/format";
import { Icon } from "./primitives";

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ }
  };
  return (
    <button type="button" className="ewb-btn ewb-btn-icon" aria-label={done ? `${label} copied` : `Copy ${label}`} onClick={copy}>
      <Icon name={done ? "check" : "copy"} />
    </button>
  );
}

export function ProvenancePanel({ view, serverTiming }: { view: EvidenceView; serverTiming: string | null }) {
  const ev = view.evidence;
  const calc = ev.calculation;
  const al = ev.comparison.alignment;
  return (
    <div className="ewb-prov">
      <dl className="ewb-kv">
        <div><dt>evidence_id</dt><dd className="ewb-mono ewb-id">{ev.evidence_id}<CopyButton text={ev.evidence_id} label="evidence id" /></dd></div>
        <div><dt>Contract</dt><dd className="ewb-mono">{ev.contract_version} · {ev.evidence_type}</dd></div>
        <div><dt>Builder</dt><dd className="ewb-mono">{calc.evidence_builder_version}</dd></div>
        <div><dt>Attribution</dt><dd className="ewb-mono">{calc.attribution_version}</dd></div>
        <div><dt>Lap distance</dt><dd className="ewb-mono">{calc.lap_distance_version}</dd></div>
        <div><dt>Input digest</dt><dd className="ewb-mono ewb-break" title={ev.provenance.input_digest}>{ev.provenance.input_digest}</dd></div>
        {serverTiming && <div><dt>Server timing</dt><dd className="ewb-mono">{serverTiming}</dd></div>}
      </dl>

      <details className="ewb-details">
        <summary><Icon name="chevronDown" />Lineage chain ({ev.provenance.chain.length} steps)</summary>
        <ol className="ewb-chain">{ev.provenance.chain.map((c) => <li key={c} className="ewb-mono">{c}</li>)}</ol>
      </details>

      <details className="ewb-details">
        <summary><Icon name="chevronDown" />Identity checks ({ev.provenance.identity_checks.length})</summary>
        <ul className="ewb-checks">{ev.provenance.identity_checks.map((c) => <li key={c}><Icon name="check" size={12} />{c}</li>)}</ul>
      </details>

      <details className="ewb-details">
        <summary><Icon name="chevronDown" />Laps and telemetry windows</summary>
        <div className="ewb-scroll-x">
          <table className="ewb-etable">
            <thead><tr><th scope="col">Driver</th><th scope="col">Lap</th><th scope="col">Lap start</th><th scope="col">Telemetry first → last</th><th scope="col">Samples</th></tr></thead>
            <tbody>
              {ev.provenance.laps.map((l) => (
                <tr key={`${l.driver_number}-${l.lap_number}`}>
                  <th scope="row">#{l.driver_number}</th><td>{l.lap_number}</td><td>{fmtClock(l.lap_started_at)}</td>
                  <td>{fmtClock(l.telemetry_first_ts)} → {fmtClock(l.telemetry_last_ts)}</td><td>{l.sample_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <details className="ewb-details">
        <summary><Icon name="chevronDown" />Alignment anchors (official sector lines)</summary>
        {al.anchors.length === 0 ? <p className="ewb-muted">No anchors: the bound is a provisional default.</p> : (
          <div className="ewb-scroll-x">
            <table className="ewb-etable">
              <thead><tr><th scope="col">Line</th><th scope="col">#{view.a} axis</th><th scope="col">#{view.b} axis</th><th scope="col">Misalignment</th></tr></thead>
              <tbody>
                {al.anchors.map((a) => (
                  <tr key={a.line}>
                    <th scope="row">{a.line}</th><td>{fmtMetres(a.distance_a_m, view.normalized, 1)}</td>
                    <td>{fmtMetres(a.distance_b_m, view.normalized, 1)}</td><td>{fmtMetres(a.misalignment_m, view.normalized, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ewb-small ewb-muted">
          E = {fmtMetres(al.misalignment_bound_m, view.normalized, 2)} (largest anchor misalignment) ·
          D = {fmtMetres(al.within_segment_change_bound_m, view.normalized, 2)} (within-segment bound)
        </p>
      </details>
    </div>
  );
}
