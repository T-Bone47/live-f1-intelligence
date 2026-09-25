/**
 * Segment timeline: every segment in lap order, one row each.
 *
 * Rows are toggle buttons with a roving tabindex: arrow keys move the
 * selection, Home/End jump, Escape clears. The band gauge draws the change
 * against its own uncertainty band (the band is always the same width), so a
 * marker inside the hatched track reads "within band" at a glance; the
 * words come from the contract's `significant` flag.
 */

import { memo, useRef, type KeyboardEvent } from "react";
import type { Segment } from "../../evidence/types";
import type { EvidenceView } from "../../evidence/viewModel";
import { changeFavours, fmtBand, fmtDelta, fmtMetreRange, isNum } from "../../evidence/format";
import { STATUS_TEXT } from "../../evidence/vocabulary";
import { SignificanceBadge } from "./primitives";

function BandGauge({ seg }: { seg: Segment }) {
  if (seg.direction === "NO_DATA" || !isNum(seg.accumulated_change_s) || !isNum(seg.uncertainty_s) || seg.uncertainty_s <= 0) {
    return <span className="ewb-gauge is-nodata" aria-hidden="true" />;
  }
  // Track = ±band occupies the middle 60 %; beyond it the marker sits outside the track.
  const ratio = seg.accumulated_change_s / seg.uncertainty_s;
  const pos = 50 + Math.max(-1.6, Math.min(1.6, ratio)) * 30;
  const side = seg.accumulated_change_s < 0 ? "a" : "b";
  return (
    <span className={`ewb-gauge ${seg.significant ? "is-significant" : ""}`} aria-hidden="true">
      <span className="ewb-gauge-track" />
      <span className="ewb-gauge-zero" />
      <span className={`ewb-gauge-mark is-${side}`} style={{ left: `${pos}%` }} />
    </span>
  );
}

interface Props {
  view: EvidenceView;
  selected: string | null;
  onSelect: (label: string | null) => void;
}

export const SegmentTimeline = memo(function SegmentTimeline({ view, selected, onSelect }: Props) {
  const listRef = useRef<HTMLOListElement>(null);
  const segs = view.segments;
  const focusIndex = Math.max(0, segs.findIndex((s) => s.label === selected));

  const move = (i: number) => {
    const next = segs[Math.max(0, Math.min(segs.length - 1, i))];
    onSelect(next.label);
    listRef.current?.querySelectorAll<HTMLButtonElement>("button.ewb-row")[segs.indexOf(next)]?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    switch (e.key) {
      case "ArrowDown": case "ArrowRight": e.preventDefault(); move(i + 1); break;
      case "ArrowUp": case "ArrowLeft": e.preventDefault(); move(i - 1); break;
      case "Home": e.preventDefault(); move(0); break;
      case "End": e.preventDefault(); move(segs.length - 1); break;
      case "Escape": onSelect(null); break;
    }
  };

  return (
    <div className="ewb-timeline">
      <div className="ewb-row ewb-row-head" aria-hidden="true">
        <span>Seg</span><span className="ewb-col-range">Range</span><span className="ewb-col-enter">Gap entering</span>
        <span>Change</span><span className="ewb-col-band">Band</span><span className="ewb-col-gauge">Change vs band</span>
        <span className="ewb-col-status">Evidence state</span>
      </div>
      <ol ref={listRef} className="ewb-rows" aria-label="Segments in lap order. Arrow keys move, Escape clears.">
        {segs.map((s, i) => {
          const isSel = s.label === selected;
          const noData = s.direction === "NO_DATA";
          const favours = changeFavours(s.accumulated_change_s, view.a, view.b);
          return (
            <li key={s.segment_id}>
              <button type="button"
                      className={`ewb-row ${isSel ? "is-selected" : ""} ${noData ? "is-nodata" : ""} ${s.significant ? "is-significant" : ""}`}
                      aria-pressed={isSel} tabIndex={i === focusIndex ? 0 : -1}
                      onClick={() => onSelect(isSel ? null : s.label)} onKeyDown={(e) => onKey(e, i)}>
                <span className="ewb-row-label">{s.label}</span>
                <span className="ewb-col-range ewb-mono">{fmtMetreRange(s.distance_start_m, s.distance_end_m, view.normalized)}</span>
                <span className="ewb-col-enter ewb-mono">{fmtDelta(s.inherited_gap_s)}</span>
                <span className="ewb-mono ewb-row-change">
                  {noData ? "No data" : fmtDelta(s.accumulated_change_s)}
                  {favours && !noData && <span className="ewb-sr">, {favours}</span>}
                </span>
                <span className="ewb-col-band ewb-mono">{fmtBand(s.uncertainty_s)}</span>
                <span className="ewb-col-gauge"><BandGauge seg={s} /></span>
                <span className="ewb-col-status">
                  <SignificanceBadge significant={s.significant} noData={noData} />
                  {!noData && s.attribution_status !== "NOT_SIGNIFICANT" && (
                    <span className="ewb-row-status">{STATUS_TEXT[s.attribution_status].label}</span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
});
