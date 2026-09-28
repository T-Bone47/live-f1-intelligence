/**
 * Track context (Phase 12C): where the selected segment ran on the validated
 * circuit, per driver. Every path is the backend's evidence_spatial_v1 extent
 * (placed by that driver's own first and last sample times in the segment);
 * NOT_PLACED extents are listed with their reason and never drawn. The
 * normalized evidence distance is never used as a position.
 */

import { memo, useMemo, type KeyboardEvent } from "react";
import { mapFit } from "../spatial/geometry";
import { useWidth } from "../command/useWidth";
import { REASON_WORDS, type Extent, type TrackContextView } from "../../evidence/spatial";
import type { EvidenceView } from "../../evidence/viewModel";

const path = (pts: [number, number][]) => pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");

export const TrackContext = memo(function TrackContext({ ctx, view, selected, onSelect }: {
  ctx: TrackContextView; view: EvidenceView; selected: string | null; onSelect: (label: string) => void;
}) {
  const [frameRef, width] = useWidth<HTMLDivElement>(360);
  const track = ctx.status === "ready" ? ctx.track : null;
  const fit = useMemo(() => (track ? mapFit(track, width) : null), [track, width]);
  const cmp = view.evidence.comparison;
  const who = { a: `#${cmp.driver_a.driver_number} lap ${cmp.driver_a.lap_number}`,
                b: `#${cmp.driver_b.driver_number} lap ${cmp.driver_b.lap_number}` };

  if (ctx.status !== "ready" || !track || !ctx.placed || !fit) {
    if (ctx.status === "loading" || ctx.status === "idle") {
      return <div ref={frameRef} className="tc-skeleton" aria-busy="true" aria-label="Loading track context" />;
    }
    return (
      <div ref={frameRef} className="tc-state" role="status">
        <p className="tc-state-title">{ctx.status === "error" ? "Track context could not be loaded" : "Track context unavailable"}</p>
        <p className="tc-muted">{ctx.message ?? "No validated track for this session."}</p>
        {ctx.reasons.length > 0 && <ul className="tc-reasons">{ctx.reasons.map((r) => <li key={r}><code>{r}</code></li>)}</ul>}
        {ctx.status === "error" && <button type="button" className="ewb-btn ewb-btn-ghost" onClick={ctx.retry}>Retry</button>}
      </div>
    );
  }

  const px = (xy: number[]) => fit.toPx(xy[0], xy[1]);
  const circuit = path((track.reference?.polyline ?? []).map((p) => px(p)));
  const seg = selected ? ctx.placed.segments.find((s) => s.label === selected) ?? null : null;
  const drawn = seg ? (["a", "b"] as const).filter((side) => seg[side].status === "PLACED") : [];
  const missing = ctx.placed.segments.flatMap((s) => (["a", "b"] as const)
    .filter((side) => s[side].status === "NOT_PLACED").map((side) => ({ s, side, e: s[side] as Extent })));
  const key = (label: string) => (e: KeyboardEvent<SVGGElement>) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(label); }
  };

  return (
    <div ref={frameRef} className="tc-frame">
      <svg className="tc-map" width={fit.width} height={fit.height} viewBox={`0 0 ${fit.width} ${fit.height}`}
           role="group" aria-label={`Track context${seg ? `, ${seg.label}` : ""}`}>
        <path className="tc-circuit" d={circuit} />
        {ctx.placed.segments.map((s) => {
          const side = s.a.status === "PLACED" ? "a" : s.b.status === "PLACED" ? "b" : null;
          if (!side) return null;
          const [x, y] = px(s[side].from_xy!);
          return (
            <g key={s.segment_id} className={`tc-tick${s.label === selected ? " is-selected" : ""}`} role="button" tabIndex={0}
               aria-label={`${s.label}, ${who[side]}, placed by time`} aria-pressed={s.label === selected}
               onClick={() => onSelect(s.label)} onKeyDown={key(s.label)} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`}>
              <circle r={9} className="tc-hit" />
              <circle r={2.6} className="tc-dot" />
            </g>
          );
        })}
        {seg && drawn.map((side) => {
          const e = seg[side];
          const [tx, ty] = px(e.to_xy!);
          return (
            <g key={side}>
              <path className={`tc-extent is-${side}`} data-side={side} d={path(e.polyline!.map((p) => px(p)))} />
              {/* A above the path end, B below it: the feed reports one shared line, so ends often meet */}
              <text className={`tc-mono is-${side}`} x={tx + 6} y={side === "a" ? ty - 6 : ty + 14}>{side.toUpperCase()}</text>
            </g>
          );
        })}
      </svg>
      <p className="tc-muted tc-caption">
        Extents placed by each driver's own sample times in the segment, not by the normalized distance axis.
        {seg ? ` ${seg.label}: A ${who.a} solid, B ${who.b} dashed.` : " Select a segment to see its extents."}
      </p>
      {missing.length > 0 && (
        <ul className="tc-missing">
          {missing.map(({ s, side, e }) => (
            <li key={`${s.segment_id}-${side}`}>{`${s.label} · ${side.toUpperCase()} ${who[side]} · not placed: ${REASON_WORDS[e.reason!]}`}</li>
          ))}
        </ul>
      )}
    </div>
  );
});
