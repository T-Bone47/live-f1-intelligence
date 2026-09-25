/**
 * Δt vs NORMALIZED lap distance — the workbench's centrepiece.
 *
 * evidence_v1 carries Δt only at segment boundaries (inherited_gap_s at
 * x_start, delta_end_s at x_end). The chart plots exactly those points and
 * joins them with chords that are labelled as NOT a measured curve. Each
 * segment's uncertainty band spans inherited_gap_s ± uncertainty_s: a chord
 * that stays inside it is a change that is not significant. Styling follows
 * the contract's `significant` flag; nothing is recomputed.
 */

import { memo, useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { Segment } from "../../evidence/types";
import type { EvidenceView } from "../../evidence/viewModel";
import { aheadOf, fmtBand, fmtDelta, fmtMetres, fmtX, isNum } from "../../evidence/format";
import { familyText, signalText } from "../../evidence/vocabulary";
import { linear, niceTicks, useElementWidth, useTweenedDomain } from "./chartGeometry";
import { Icon } from "./primitives";

/** A segment boundary, with the evidence's own x, metres and Δt. */
interface Boundary { x: number; metres: number; delta: number; before: Segment | null; after: Segment | null }

function boundaries(segs: Segment[]): Boundary[] {
  const out: Boundary[] = [];
  segs.forEach((s, i) => {
    if (i === 0 && isNum(s.inherited_gap_s)) {
      out.push({ x: s.x_start, metres: s.distance_start_m, delta: s.inherited_gap_s, before: null, after: s });
    }
    if (isNum(s.delta_end_s)) {
      out.push({ x: s.x_end, metres: s.distance_end_m, delta: s.delta_end_s, before: s, after: segs[i + 1] ?? null });
    }
  });
  return out;
}

function yExtent(view: EvidenceView): [number, number] {
  const vals = [0];
  for (const s of view.segments) {
    if (isNum(s.inherited_gap_s)) {
      vals.push(s.inherited_gap_s);
      if (isNum(s.uncertainty_s)) vals.push(s.inherited_gap_s - s.uncertainty_s, s.inherited_gap_s + s.uncertainty_s);
    }
    if (isNum(s.delta_end_s)) vals.push(s.delta_end_s);
  }
  if (isNum(view.evidence.comparison.lap_delta_s)) vals.push(view.evidence.comparison.lap_delta_s);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo || 0.1) * 0.08;
  return [lo - pad, hi + pad];
}

interface Props {
  view: EvidenceView;
  selected: string | null;
  onSelect: (label: string | null) => void;
  onStep: (step: number) => void;
}

export const DeltaChart = memo(function DeltaChart({ view, selected, onSelect, onStep }: Props) {
  const uid = useId().replace(/:/g, "");
  const { ref, width } = useElementWidth<HTMLDivElement>();
  const [focus, setFocus] = useState(true);
  const [hover, setHover] = useState<number | null>(null);
  const segs = view.segments;
  const pts = useMemo(() => boundaries(segs), [segs]);
  const [y0, y1] = useMemo(() => yExtent(view), [view]);

  const selIdx = selected == null ? -1 : segs.findIndex((s) => s.label === selected);
  const target: [number, number] = focus && selIdx >= 0
    ? [segs[Math.max(0, selIdx - 1)].x_start, segs[Math.min(segs.length - 1, selIdx + 1)].x_end]
    : [0, 1];
  const [dx0, dx1] = useTweenedDomain(target);

  const compact = width < 560;
  const H = compact ? 250 : 310;
  const m = { top: 24, right: compact ? 10 : 18, bottom: 50, left: compact ? 46 : 58 };
  const pw = Math.max(40, width - m.left - m.right);
  const ph = H - m.top - m.bottom;
  const sx = linear(dx0, dx1, m.left, m.left + pw);
  const sy = linear(y0, y1, m.top + ph, m.top);
  const yTicks = niceTicks(y0, y1, compact ? 4 : 6);
  const xTicks = niceTicks(dx0, dx1, compact ? 4 : 8).filter((t) => t >= 0 && t <= 1);
  const inView = (x: number) => x >= dx0 - 1e-9 && x <= dx1 + 1e-9;
  const zeroY = sy(0);
  const sel = selIdx >= 0 ? segs[selIdx] : null;
  const lapDelta = view.evidence.comparison.lap_delta_s;

  const xFromPointer = (e: PointerEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return dx0 + ((e.clientX - r.left) / (r.width || 1)) * (dx1 - dx0);
  };
  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const x = xFromPointer(e);
    let best = -1, bestD = Infinity;
    pts.forEach((p, i) => { const d = Math.abs(p.x - x); if (d < bestD && inView(p.x)) { best = i; bestD = d; } });
    setHover(best >= 0 ? best : null);
  };
  const onClick = (e: PointerEvent<SVGRectElement>) => {
    const x = xFromPointer(e);
    const s = segs.find((g) => x >= g.x_start && x <= g.x_end);
    if (s) onSelect(s.label);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowRight") { e.preventDefault(); onStep(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); onStep(-1); }
    else if (e.key === "Escape") onSelect(null);
  };

  const hp = hover != null ? pts[hover] : null;
  const summary = `Delta over normalized lap distance for #${view.a} (A) minus #${view.b} (B), ${segs.length} segments; `
    + `${segs.filter((s) => s.significant).length} significant. Values are listed in the table that follows.`;

  return (
    <div className="ewb-chart" ref={ref}>
      <div className="ewb-chart-toolbar">
        <p className="ewb-axis-note">
          <strong>Δt</strong> = elapsed A − elapsed B (s) over <strong>normalized lap distance</strong> — not track position
        </p>
        <div className="ewb-btn-row">
          <button type="button" className="ewb-btn ewb-btn-ghost" aria-pressed={focus}
                  disabled={!sel} onClick={() => setFocus((f) => !f)}>
            <Icon name={focus && sel ? "zoomOut" : "zoomIn"} />{focus && sel ? "Full lap" : "Focus selection"}
          </button>
          <button type="button" className="ewb-btn ewb-btn-ghost" disabled={!sel} onClick={() => onSelect(null)}>
            <Icon name="x" />Reset view
          </button>
        </div>
      </div>

      <div className="ewb-chart-frame" tabIndex={0} role="group"
           aria-label={`${summary} Use left and right arrow keys to step through segments, Escape to clear.`}
           onKeyDown={onKey}>
        <svg width={width} height={H} className="ewb-chart-svg" aria-hidden="true">
          <defs>
            <clipPath id={`clip${uid}`}><rect x={m.left} y={m.top} width={pw} height={ph} /></clipPath>
            <pattern id={`hatch${uid}`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" className="ewb-hatch-line" />
            </pattern>
            <pattern id={`nodata${uid}`} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
              <line x1="0" y1="0" x2="0" y2="8" className="ewb-nodata-line" />
            </pattern>
          </defs>

          <g clipPath={`url(#clip${uid})`}>
            {zeroY > m.top && <rect x={m.left} y={m.top} width={pw} height={Math.max(0, Math.min(ph, zeroY - m.top))} className="ewb-region-b" />}
            {zeroY < m.top + ph && <rect x={m.left} y={Math.max(m.top, zeroY)} width={pw} height={m.top + ph - Math.max(m.top, zeroY)} className="ewb-region-a" />}

            {segs.map((s) => {
              const x0 = sx(s.x_start), w = Math.max(0, sx(s.x_end) - x0);
              const isSel = s.label === selected;
              return (
                <g key={s.segment_id} className={`ewb-seg ${isSel ? "is-selected" : ""} ${s.direction === "NO_DATA" ? "is-nodata" : ""}`}>
                  <rect x={x0} y={m.top} width={w} height={ph} className="ewb-seg-bg" />
                  {s.direction === "NO_DATA" && <rect x={x0} y={m.top} width={w} height={ph} fill={`url(#nodata${uid})`} />}
                  {isNum(s.inherited_gap_s) && isNum(s.uncertainty_s) && (
                    <rect x={x0} width={w} y={sy(s.inherited_gap_s + s.uncertainty_s)}
                          height={Math.max(0, sy(s.inherited_gap_s - s.uncertainty_s) - sy(s.inherited_gap_s + s.uncertainty_s))}
                          fill={`url(#hatch${uid})`} className="ewb-band" />
                  )}
                  <line x1={x0} x2={x0} y1={m.top} y2={m.top + ph} className="ewb-seg-edge" />
                </g>
              );
            })}

            {yTicks.map((t) => <line key={t} x1={m.left} x2={m.left + pw} y1={sy(t)} y2={sy(t)} className="ewb-gridline" />)}
            <line x1={m.left} x2={m.left + pw} y1={zeroY} y2={zeroY} className="ewb-zero" />

            {segs.map((s) => isNum(s.inherited_gap_s) && isNum(s.delta_end_s) && (
              <line key={`c${s.segment_id}`} x1={sx(s.x_start)} y1={sy(s.inherited_gap_s)} x2={sx(s.x_end)} y2={sy(s.delta_end_s)}
                    className={`ewb-chord ${s.significant ? "is-significant" : "is-not-significant"} ${s.label === selected ? "is-selected" : ""}`} />
            ))}

            {sel && isNum(sel.accumulation_midpoint_x) && (
              <line x1={sx(sel.accumulation_midpoint_x)} x2={sx(sel.accumulation_midpoint_x)} y1={m.top} y2={m.top + ph} className="ewb-midpoint" />
            )}

            {pts.map((p, i) => (
              <circle key={i} cx={sx(p.x)} cy={sy(p.delta)} r={hover === i ? 5 : 3.5}
                      className={`ewb-point ${p.delta < 0 ? "is-a" : p.delta > 0 ? "is-b" : ""}`} />
            ))}

            {isNum(lapDelta) && inView(1) && (
              <path d={`M${sx(1)},${sy(lapDelta) - 6}l6,6l-6,6l-6,-6z`} className="ewb-official" />
            )}

            {hp && <line x1={sx(hp.x)} x2={sx(hp.x)} y1={m.top} y2={m.top + ph} className="ewb-crosshair" />}
          </g>

          {zeroY - m.top > 14 && <text x={m.left + 6} y={m.top + 12} className="ewb-region-label is-b">#{view.b} ahead ▲</text>}
          {m.top + ph - zeroY > 14 && <text x={m.left + 6} y={m.top + ph - 6} className="ewb-region-label is-a">#{view.a} ahead ▼</text>}

          {yTicks.map((t) => (
            <text key={t} x={m.left - 6} y={sy(t) + 3} textAnchor="end" className="ewb-tick">{fmtDelta(t, 2).replace(" s", "")}</text>
          ))}
          <text transform={`translate(12 ${m.top + ph / 2}) rotate(-90)`} textAnchor="middle" className="ewb-axis-title">Δt (s)</text>

          {view.evidence.attribution.sectors.flatMap((sec) => ([["a", sec.line_x_a], ["b", sec.line_x_b]] as const).map(([side, x]) =>
            isNum(x) && inView(x) ? (
              <line key={`${sec.sector}${side}`} x1={sx(x)} x2={sx(x)} y1={m.top - 9} y2={m.top}
                    className={`ewb-sector-tick is-${side}`} />
            ) : null))}
          {view.evidence.attribution.sectors.map((sec) => isNum(sec.line_x_a) && inView(sec.line_x_a) && (
            <text key={`st${sec.sector}`} x={sx(sec.line_x_a) + 4} y={m.top - 12} className="ewb-sector-label">S{sec.sector} line (A/B)</text>
          ))}

          {sel && sel.braking && inView(sel.braking.zone_start_x) && (
            <rect x={sx(sel.braking.zone_start_x)} y={m.top + ph + 3} height={5}
                  width={Math.max(2, sx(sel.braking.zone_end_x) - sx(sel.braking.zone_start_x))} className="ewb-lane-brake" />
          )}
          {sel?.onset_order.map((o, i) => inView(o.x) && (
            <line key={i} x1={sx(o.x)} x2={sx(o.x)} y1={m.top + ph + 1} y2={m.top + ph + 11} className={`ewb-lane-tick is-${o.family}`}>
              <title>{`${signalText(o.signal)} (${familyText(o.family)}) at ${fmtX(o.x)} — temporal association`}</title>
            </line>
          ))}

          {xTicks.map((t) => (
            <text key={t} x={sx(t)} y={m.top + ph + 24} textAnchor="middle" className="ewb-tick">{t.toFixed(t === 0 || t === 1 ? 1 : 2)}</text>
          ))}
          {segs.map((s) => {
            const w = sx(Math.min(s.x_end, dx1)) - sx(Math.max(s.x_start, dx0));
            if (w < 26 || s.x_end < dx0 || s.x_start > dx1) return null;
            const cx = (sx(Math.max(s.x_start, dx0)) + sx(Math.min(s.x_end, dx1))) / 2;
            return <text key={`l${s.segment_id}`} x={cx} y={m.top + ph + 40} textAnchor="middle"
                         className={`ewb-seg-label ${s.label === selected ? "is-selected" : ""}`}>{s.label}</text>;
          })}

          <rect x={m.left} y={m.top} width={pw} height={ph} className="ewb-hit"
                onPointerMove={onMove} onPointerLeave={() => setHover(null)} onPointerUp={onClick} />
        </svg>

        {hp && (
          <div className="ewb-tooltip" role="presentation"
               style={{ left: Math.min(Math.max(sx(hp.x), 96), width - 96), top: Math.max(sy(hp.delta) - 12, 4) }}>
            <p className="ewb-tooltip-title">
              {hp.before ? `End of ${hp.before.label}` : `Start of ${hp.after?.label}`}
              {hp.before && hp.after ? ` · start of ${hp.after.label}` : ""}
            </p>
            <p className="ewb-mono">{fmtX(hp.x)} · {fmtMetres(hp.metres, view.normalized)}</p>
            <p className="ewb-mono">Δt {fmtDelta(hp.delta)} · {aheadOf(hp.delta, view.a, view.b)}</p>
          </div>
        )}
      </div>

      <ul className="ewb-legend" aria-label="Chart legend">
        <li><span className="ewb-key ewb-key-point" />Δt at a segment boundary (evidence)</li>
        <li><span className="ewb-key ewb-key-chord-ns" />Chord, not significant — not a measured curve</li>
        <li><span className="ewb-key ewb-key-chord-sig" />Chord, significant</li>
        <li><span className="ewb-key ewb-key-band" />Uncertainty band: inherited gap ± band</li>
        <li><span className="ewb-key ewb-key-official" />Official lap Δ (class B) at x 1.0</li>
        <li><span className="ewb-key ewb-key-nodata" />No data</li>
        {sel && <li><span className="ewb-key ewb-key-mid" />½ change accumulated ({sel.label})</li>}
      </ul>

      <BoundaryTable view={view} />
    </div>
  );
});

function BoundaryTable({ view }: { view: EvidenceView }) {
  // Wrapped: tables ignore width: 1px, so a visually-hidden <table> would still add scroll width.
  return (
    <div className="ewb-sr">
    <table>
      <caption>Δt at segment boundaries, A = #{view.a}, B = #{view.b}</caption>
      <thead><tr><th>Segment</th><th>Range</th><th>Δt entering</th><th>Δt leaving</th><th>Band</th><th>Significant</th></tr></thead>
      <tbody>
        {view.segments.map((s) => (
          <tr key={s.segment_id}>
            <th scope="row">{s.label}</th>
            <td>{fmtX(s.x_start)} to {fmtX(s.x_end)}</td>
            <td>{fmtDelta(s.inherited_gap_s)}</td>
            <td>{fmtDelta(s.delta_end_s)}</td>
            <td>{fmtBand(s.uncertainty_s)}</td>
            <td>{s.direction === "NO_DATA" ? "no data" : s.significant ? "yes" : "no"}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}
