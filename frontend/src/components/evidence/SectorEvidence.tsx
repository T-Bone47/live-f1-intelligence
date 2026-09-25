/**
 * Sectors: official timing (class B) and engine change (class C) side by
 * side, never merged. NOT_COVERED sectors show no engine value — none is
 * manufactured.
 */

import type { EvidenceView } from "../../evidence/viewModel";
import { aheadOf, fmtDelta, fmtLapTime, fmtMetres, fmtSignedNum } from "../../evidence/format";
import { ClassBadge } from "./primitives";

export function SectorEvidence({ view, selected, onSelect }: {
  view: EvidenceView; selected: string | null; onSelect: (label: string) => void;
}) {
  return (
    <div className="ewb-sectors">
      {view.evidence.attribution.sectors.map((sec) => {
        const covered = sec.coverage === "COVERED";
        return (
          <article key={sec.sector_id} className={`ewb-sector ${covered ? "" : "is-not-covered"}`} aria-labelledby={`sec-${sec.sector}`}>
            <header className="ewb-sector-head">
              <h3 id={`sec-${sec.sector}`}>S{sec.sector}</h3>
              <span className={`ewb-coverage ${covered ? "is-covered" : "is-not-covered"}`}>{covered ? "Covered" : "Not covered"}</span>
            </header>
            <dl className="ewb-sector-grid">
              <div><dt>#{view.a} official</dt><dd className="ewb-mono">{fmtLapTime(sec.official_a_s)}</dd></div>
              <div><dt>#{view.b} official</dt><dd className="ewb-mono">{fmtLapTime(sec.official_b_s)}</dd></div>
              <div className="is-wide">
                <dt>Official Δ <ClassBadge cls={sec.official_provenance_class} /></dt>
                <dd className="ewb-mono ewb-strong">{fmtDelta(sec.official_delta_s)} <span className="ewb-muted">{aheadOf(sec.official_delta_s, view.a, view.b) ?? ""}</span></dd>
              </div>
              <div className="is-wide">
                <dt>Engine change <ClassBadge cls={sec.engine_provenance_class} /></dt>
                <dd className="ewb-mono">{covered ? fmtDelta(sec.engine_change_s) : "Not available — telemetry does not reach this sector line"}</dd>
              </div>
              {covered && (
                <>
                  <div><dt>Engine − official</dt><dd className="ewb-mono">{fmtSignedNum(sec.engine_minus_official_s)} s</dd></div>
                  <div><dt>Line misalignment</dt><dd className="ewb-mono">{fmtMetres(sec.line_misalignment_m, view.normalized, 2)}</dd></div>
                </>
              )}
            </dl>
            <p className="ewb-label">Segments touching S{sec.sector}</p>
            <ul className="ewb-chip-row">
              {sec.segment_ids.map((id) => {
                const seg = view.byId.get(id);
                if (!seg) return null;
                return (
                  <li key={id}>
                    <button type="button" className={`ewb-chip ${seg.label === selected ? "is-selected" : ""}`}
                            aria-pressed={seg.label === selected} onClick={() => onSelect(seg.label)}>{seg.label}</button>
                  </li>
                );
              })}
            </ul>
          </article>
        );
      })}
    </div>
  );
}
