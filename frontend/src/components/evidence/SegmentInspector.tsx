/**
 * Selected-segment inspector: time accounting, interpretation state, signal
 * onset order, engineering evidence and segment provenance — in that order,
 * so "what the data supports" is read before "what differed".
 */

import type { Segment } from "../../evidence/types";
import type { EvidenceView } from "../../evidence/viewModel";
import {
  aheadOf, changeFavours, fmtBand, fmtClock, fmtDelta, fmtMetreRange, fmtMetres, fmtX, isNum,
} from "../../evidence/format";
import {
  DIRECTION_DETAIL, DIRECTION_TEXT, RELATION_TEXT, STATUS_TEXT, familyText, signalText,
} from "../../evidence/vocabulary";
import { isSupportedReference } from "../../evidence/api";
import { EngineeringEvidence } from "./EngineeringEvidence";
import {
  AssociationTag, ClassBadge, ConfidenceTag, Icon, Readout, SignificanceBadge, StatusBadge,
} from "./primitives";

interface Props {
  view: EvidenceView;
  segment: Segment | null;
  onStep: (step: number) => void;
  onClear: () => void;
  drillOpen: boolean;
  onToggleDrill: () => void;
}

function Verdict({ seg }: { seg: Segment }) {
  if (seg.direction === "NO_DATA") {
    return <p className="ewb-verdict is-nodata"><Icon name="ban" />No telemetry coverage: no delta exists here and nothing is attributed.</p>;
  }
  const change = isNum(seg.accumulated_change_s) ? Math.abs(seg.accumulated_change_s).toFixed(3) : "—";
  return seg.significant
    ? <p className="ewb-verdict is-significant"><Icon name="circleDot" />Significant: the measured change ({change} s) exceeds its {fmtBand(seg.uncertainty_s)} band.</p>
    : <p className="ewb-verdict is-not-significant"><Icon name="circleMinus" />Not significant under the current uncertainty bound: the measured change ({change} s) lies within {fmtBand(seg.uncertainty_s)}.</p>;
}

export function SegmentInspector({ view, segment: s, onStep, onClear, drillOpen, onToggleDrill }: Props) {
  if (!s) {
    return (
      <aside className="ewb-inspector is-empty" aria-label="Segment inspector">
        <p className="ewb-eyebrow">Segment inspector</p>
        <p className="ewb-empty-text">Select a segment in the chart or the timeline to inspect its time accounting and engineering evidence.</p>
        <p className="ewb-hint">Keys: <kbd>←</kbd>/<kbd>→</kbd> in the chart or <kbd>↑</kbd>/<kbd>↓</kbd> in the timeline · <kbd>[</kbd>/<kbd>]</kbd> anywhere · <kbd>Esc</kbd> clears</p>
      </aside>
    );
  }
  const noData = s.direction === "NO_DATA";
  const idx = view.segments.indexOf(s);
  const sectors = view.sectorsBySegment.get(s.segment_id) ?? [];
  const refsOk = s.telemetry_references.length > 0 && s.telemetry_references.every(isSupportedReference);

  return (
    <aside className="ewb-inspector" aria-label={`Segment ${s.label} inspector`}>
      <header className="ewb-insp-head">
        <div>
          <p className="ewb-eyebrow">Segment {idx + 1} of {view.segments.length}{sectors.length > 0 && ` · in ${sectors.map((x) => `S${x.sector}`).join(", ")}`}</p>
          <h2 className="ewb-insp-title" aria-live="polite">{s.label}</h2>
          <p className="ewb-mono ewb-insp-range">{fmtMetreRange(s.distance_start_m, s.distance_end_m, view.normalized)} · {fmtX(s.x_start)}–{s.x_end.toFixed(3)}</p>
        </div>
        <div className="ewb-btn-row">
          <button type="button" className="ewb-btn ewb-btn-icon" aria-label="Previous segment" disabled={idx <= 0} onClick={() => onStep(-1)}><Icon name="chevronLeft" /></button>
          <button type="button" className="ewb-btn ewb-btn-icon" aria-label="Next segment" disabled={idx >= view.segments.length - 1} onClick={() => onStep(1)}><Icon name="chevronRight" /></button>
          <button type="button" className="ewb-btn ewb-btn-icon" aria-label="Clear selection" onClick={onClear}><Icon name="x" /></button>
        </div>
      </header>

      <div className="ewb-insp-badges">
        <SignificanceBadge significant={s.significant} noData={noData} />
        {/* NOT_SIGNIFICANT / NO_DATA already read from the significance badge */}
        {s.attribution_status !== "NOT_SIGNIFICANT" && s.attribution_status !== "NO_DATA" && (
          <StatusBadge status={s.attribution_status} />
        )}
        <ClassBadge cls={s.provenance_class} />
        <ConfidenceTag level={s.telemetry_confidence} />
      </div>

      <h3 className="ewb-subhead">Time accounting</h3>
      <dl className="ewb-accounting-grid">
        <Readout label="Gap entering" value={fmtDelta(s.inherited_gap_s)}
                 sub={<>{aheadOf(s.inherited_gap_s, view.a, view.b) ?? "unavailable"} · existed before {s.label}</>} />
        <Readout label="Change in segment" value={noData ? "No data" : fmtDelta(s.accumulated_change_s)}
                 sub={noData ? "not measured" : `measured · ${changeFavours(s.accumulated_change_s, view.a, view.b)}`} />
        <Readout label="Uncertainty band" value={fmtBand(s.uncertainty_s)} sub="the change must exceed this" />
        <Readout label="Gap leaving" value={fmtDelta(s.delta_end_s)}
                 sub={aheadOf(s.delta_end_s, view.a, view.b) ?? "no data"} />
      </dl>
      <Verdict seg={s} />

      <h3 className="ewb-subhead">Interpretation state</h3>
      <p className="ewb-state"><strong>{STATUS_TEXT[s.attribution_status].label}.</strong> {STATUS_TEXT[s.attribution_status].detail}</p>
      <p className="ewb-state-sub">Direction: {DIRECTION_TEXT[s.direction]} — {DIRECTION_DETAIL[s.direction]}</p>
      {(s.primary_signal || s.supporting_signals.length > 0) && (
        <dl className="ewb-signals">
          {s.primary_signal && <div><dt>Differing family (not a cause)</dt><dd>{familyText(s.primary_signal)}</dd></div>}
          {s.supporting_signals.length > 0 && <div><dt>Supporting signals</dt><dd>{s.supporting_signals.map(familyText).join(", ")}</dd></div>}
        </dl>
      )}

      <h3 className="ewb-subhead">Signal onset order <AssociationTag /></h3>
      {s.onset_order.length === 0 ? (
        <p className="ewb-muted">No resolvable signal onsets in this segment.</p>
      ) : (
        <ol className="ewb-onsets">
          {s.onset_order.map((o, i) => (
            <li key={i} className={`is-${o.family}`}>
              <span className="ewb-family">{familyText(o.family)}</span>
              <span>{signalText(o.signal)}</span>
              <span className="ewb-mono">{fmtMetres(o.distance_m, view.normalized, 1)}</span>
              <span className="ewb-muted">{RELATION_TEXT[o.relation_to_midpoint]}</span>
            </li>
          ))}
        </ol>
      )}
      {isNum(s.accumulation_midpoint_x) && (
        <p className="ewb-muted ewb-small">Accumulation midpoint (half the change accumulated): {fmtX(s.accumulation_midpoint_x)}. Order is temporal; causality is not established.</p>
      )}

      <EngineeringEvidence view={view} seg={s} />

      <div className="ewb-insp-actions">
        <button type="button" className="ewb-btn" aria-expanded={drillOpen} aria-controls="ewb-drilldown"
                disabled={!refsOk} onClick={onToggleDrill}>
          <Icon name="activity" />{drillOpen ? "Hide telemetry" : "Inspect telemetry"}
        </button>
        {!refsOk && <span className="ewb-muted ewb-small">No supported telemetry reference for this segment.</span>}
      </div>

      <details className="ewb-details">
        <summary><Icon name="chevronDown" />Segment provenance</summary>
        <dl className="ewb-kv">
          <div><dt>segment_id</dt><dd className="ewb-mono ewb-break">{s.segment_id}</dd></div>
          <div><dt>Δ source</dt><dd className="ewb-mono">{s.provenance.delta_source}</dd></div>
          <div><dt>Grid indices</dt><dd className="ewb-mono">{s.provenance.grid_indices.join("–")}</dd></div>
          <div><dt>Samples #{view.a}</dt><dd className="ewb-mono">{s.provenance.sample_indices_a.join("–")}</dd></div>
          <div><dt>Samples #{view.b}</dt><dd className="ewb-mono">{s.provenance.sample_indices_b.join("–")}</dd></div>
          <div><dt>Window #{view.a}</dt><dd className="ewb-mono">{s.provenance.ts_range_a ? `${fmtClock(s.provenance.ts_range_a[0])} → ${fmtClock(s.provenance.ts_range_a[1])}` : "Unavailable"}</dd></div>
          <div><dt>Window #{view.b}</dt><dd className="ewb-mono">{s.provenance.ts_range_b ? `${fmtClock(s.provenance.ts_range_b[0])} → ${fmtClock(s.provenance.ts_range_b[1])}` : "Unavailable"}</dd></div>
        </dl>
      </details>
    </aside>
  );
}
