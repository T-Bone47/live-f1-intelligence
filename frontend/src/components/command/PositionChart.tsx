/**
 * Position evolution (Phase 11): each driver's backend position at every lap
 * frame up to the cursor. P1 is at the top (lower is better). A gap in a line
 * means the position was not reported - never an assumed change. Lines use
 * the provider's team colour; the second car of a team is dashed.
 *
 * Click: moves the session cursor to that lap and selects the nearest driver.
 */

import { memo, useMemo, useState, type PointerEvent } from "react";
import { driverCode, phaseLabel, phaseTone, teamColour } from "../../command/format";
import { positionHistory, type Moment } from "../../command/moment";
import type { Timeline } from "../../command/types";
import { Panel } from "./ui";
import { useWidth } from "./useWidth";

const M = { l: 34, r: 66, t: 10, b: 24 };
const ROW = 13;

function lapOf(t: Timeline, i: number): number {
  const f = t.frames[i];
  return f.kind === "START" ? 0 : f.lap ?? 0;
}

/** Last LAP frame index at or before the cursor (FINAL is not a lap boundary). */
function lastLapFrame(t: Timeline, index: number): number {
  let i = index;
  while (i > 0 && t.frames[i].kind === "FINAL") i -= 1;
  return i;
}

const Lines = memo(function Lines({ t, upTo, x, y, selected, hovered }: {
  t: Timeline; upTo: number; x: (lap: number) => number; y: (pos: number) => number;
  selected: number | null; hovered: number | null;
}) {
  const history = useMemo(() => positionHistory(t, upTo), [t, upTo]);
  const teamSeen = new Map<string, number>();
  const focus = hovered ?? selected;
  return (
    <g className="cc-pos-lines">
      {t.drivers.map((d) => {
        const series = history.get(d.driver_number) ?? [];
        const teamKey = d.team_id ?? `car-${d.driver_number}`;
        const nth = teamSeen.get(teamKey) ?? 0;
        teamSeen.set(teamKey, nth + 1);
        let path = "";
        let pen = false;
        series.forEach((p, i) => {
          if (p == null) { pen = false; return; }
          path += `${pen ? "L" : "M"}${x(lapOf(t, i)).toFixed(1)},${y(p).toFixed(1)}`;
          pen = true;
        });
        if (!path) return null;
        const dim = focus != null && focus !== d.driver_number;
        const on = focus === d.driver_number;
        return (
          <path key={d.driver_number} d={path} fill="none"
                stroke={teamColour(d) ?? "var(--text-secondary)"} strokeWidth={on ? 2.75 : 1.5}
                strokeDasharray={nth > 0 ? "5 3" : undefined} strokeLinejoin="round"
                opacity={dim ? 0.18 : 0.95} className={on ? "is-focus" : undefined} />
        );
      })}
    </g>
  );
});

export function PositionChart({ moment, selected, onSelect, onSeek }: {
  moment: Moment; selected: number | null;
  onSelect: (n: number | null) => void; onSeek: (index: number) => void;
}) {
  const t = moment.timeline;
  const [wrap, width] = useWidth<HTMLDivElement>(720);
  const [hover, setHover] = useState<{ lap: number; pos: number; driver: number | null; px: number } | null>(null);
  const n = Math.max(t.drivers.length, moment.rows.length, 2);
  const total = Math.max(t.laps_completed_max ?? 1, 1);
  const H = M.t + M.b + ROW * (n - 1) + 8;
  const plotW = Math.max(width - M.l - M.r, 60);
  const x = (lap: number) => M.l + (lap / total) * plotW;
  const y = (pos: number) => M.t + 4 + (pos - 1) * ROW;
  const upTo = lastLapFrame(t, moment.index);
  const cursorLap = lapOf(t, upTo);

  const lapFrame = useMemo(() => {
    const m = new Map<number, number>();
    t.frames.forEach((f, i) => { if (f.kind !== "FINAL") m.set(lapOf(t, i), i); });
    return m;
  }, [t]);

  const bands = useMemo(() => t.frames
    .map((f, i) => ({ i, tone: phaseTone(f.phase), f }))
    .filter((b) => b.f.kind === "LAP" && b.i <= upTo && (b.tone === "red" || b.tone === "sc" || b.tone === "vsc")),
  [t, upTo]);

  const pointer = (e: PointerEvent<SVGRectElement>) => {
    const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - box.left;
    const lap = Math.max(0, Math.min(cursorLap, Math.round(((px - M.l) / plotW) * total)));
    const pos = Math.max(1, Math.min(n, Math.round((e.clientY - box.top - M.t - 4) / ROW + 1)));
    const frame = t.frames[lapFrame.get(lap) ?? 0];
    const driver = frame.rows.find((r) => r.position === pos)?.driver_number ?? null;
    setHover({ lap, pos, driver, px });
  };

  const hoveredDriver = hover?.driver ?? null;
  return (
    <Panel id="cc-positions" title="Position evolution"
      meta={<span>positions at each leader lap end · P1 top · a gap = not reported</span>}>
      <div ref={wrap} className="cc-chart-wrap">
        <svg className="cc-pos-chart" width={width} height={H} role="img"
             aria-label={`Position by lap, laps 0 to ${cursorLap} of ${total}. Current leader ${driverCode(moment.driver.get(moment.rows[0]?.driver_number), moment.rows[0]?.driver_number ?? 0)}.`}>
          <rect x={M.l} y={M.t} width={plotW} height={H - M.t - M.b} className="cc-plot-bg" />
          {bands.map((b) => (
            <g key={b.i}>
              <rect x={x(Math.max(0, (b.f.lap ?? 1) - 1))} y={M.t} width={Math.max(2, plotW / total)}
                    height={H - M.t - M.b} className={`cc-band cc-band-${b.tone}`} />
              <text x={x((b.f.lap ?? 1) - 0.5)} y={M.t + 9} className="cc-band-label" textAnchor="middle">
                {phaseLabel(b.f.phase).replace(" FLAG", "")}
              </text>
            </g>
          ))}
          {Array.from({ length: n }, (_, i) => i + 1).filter((p) => p === 1 || p % 5 === 0).map((p) => (
            <g key={p}>
              <line x1={M.l} x2={M.l + plotW} y1={y(p)} y2={y(p)} className="cc-gridline" />
              <text x={M.l - 6} y={y(p) + 3.5} textAnchor="end" className="cc-axis">P{p}</text>
            </g>
          ))}
          {Array.from({ length: Math.floor(total / 10) + 1 }, (_, i) => i * 10).map((lap) => (
            <g key={lap}>
              <line x1={x(lap)} x2={x(lap)} y1={M.t} y2={H - M.b} className="cc-gridline cc-grid-v" />
              <text x={x(lap)} y={H - 8} textAnchor="middle" className="cc-axis">{lap === 0 ? "START" : `L${lap}`}</text>
            </g>
          ))}
          <Lines t={t} upTo={upTo} x={x} y={y} selected={selected} hovered={hoveredDriver} />
          <line x1={x(cursorLap)} x2={x(cursorLap)} y1={M.t} y2={H - M.b} className="cc-cursor-line" />
          {moment.rows.filter((r) => r.position != null).map((r) => {
            const d = moment.driver.get(r.driver_number);
            const on = (hoveredDriver ?? selected) === r.driver_number;
            return (
              <text key={r.driver_number} x={M.l + plotW + 8} y={y(r.position!) + 3.5}
                    className={`cc-pos-label${on ? " is-focus" : ""}`}>
                <tspan fill={teamColour(d) ?? "currentColor"}>■</tspan> {driverCode(d, r.driver_number)}
              </text>
            );
          })}
          <rect x={M.l} y={M.t} width={plotW} height={H - M.t - M.b} fill="transparent" className="cc-hit"
                onPointerMove={pointer} onPointerLeave={() => setHover(null)}
                onClick={() => {
                  if (!hover) return;
                  onSeek(lapFrame.get(hover.lap) ?? moment.index);
                  if (hover.driver != null) onSelect(hover.driver);
                }} />
          {hover && (
            <g className="cc-chart-tip" transform={`translate(${Math.min(hover.px + 10, width - 150)},${M.t + 6})`} pointerEvents="none">
              <rect width={138} height={34} rx={3} />
              <text x={8} y={14}>{hover.lap === 0 ? "START" : `LAP ${hover.lap}`} · P{hover.pos}</text>
              <text x={8} y={27} className="cc-chart-tip-strong">
                {hover.driver != null ? driverCode(moment.driver.get(hover.driver), hover.driver) : "not reported"}
              </text>
            </g>
          )}
        </svg>
      </div>
      <table className="cc-sr">
        <caption>Positions at the cursor ({moment.isStart ? "start" : `lap ${moment.lap}`})</caption>
        <tbody>
          {moment.rows.map((r) => (
            <tr key={r.driver_number}><th scope="row">P{r.position ?? "—"}</th>
              <td>{driverCode(moment.driver.get(r.driver_number), r.driver_number)}</td></tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
