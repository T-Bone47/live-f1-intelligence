/**
 * Car telemetry at the cursor (Phase 12C). The selected driver's STORED
 * samples in the 60 s up to the cursor, one row per channel: markers joined
 * by lines, broken (and labelled) wherever two samples are more than 2 s
 * apart. Nothing after the cursor is drawn, nothing is interpolated or
 * filled, and a channel with no samples says so. Hovering or stepping to a
 * sample reports that sample's own time; the map shows the driver's own
 * location sample at or before it (useGhost).
 *
 * The only arithmetic is pixel geometry: time and value to pixels.
 */

import { memo, useCallback, useMemo, type KeyboardEvent, type PointerEvent } from "react";
import { driverCode, fmtClockTenths, fmtInt } from "../../command/format";
import type { DriverIdentity } from "../../command/types";
import type { Channel, ChannelView, Gap, Sample } from "../../telemetry/types";
import type { GhostView } from "../../telemetry/useGhost";
import { TELEMETRY_BACK_MS, type TelemetryView } from "../../telemetry/useTelemetryWindow";
import { EmptyState, ErrorState, Panel } from "../command/ui";
import { useWidth } from "../command/useWidth";
import "./telemetry.css";

interface Row { channel: Channel; label: string; unit: string; max: number; format: (v: number) => string }

const ROWS: Row[] = [
  { channel: "speed", label: "Speed", unit: "kph", max: 360, format: (v) => `${v} kph` },
  { channel: "throttle", label: "Throttle", unit: "%", max: 100, format: (v) => `${v} %` },
  { channel: "brake", label: "Brake", unit: "as delivered", max: 100, format: (v) => `${v}` },
  { channel: "gear", label: "Gear", unit: "", max: 8, format: (v) => `${v}` },
  { channel: "rpm", label: "RPM", unit: "", max: 13000, format: (v) => fmtInt(v) },
];

const LABEL_W = 78, VALUE_W = 78, ROW_H = 38, ROW_GAP = 6, AXIS_H = 18;
/** Below this width each channel's label and value sit on a line above a full-width plot. */
const NARROW_PX = 480, HEAD_H = 16;

const GHOST_WORDS: Record<GhostView["status"], string> = {
  idle: "", loading: "locating on the map…", ready: "shown on the map",
  none: "no location sample within 2 s: not on the map", unavailable: "map unavailable",
  error: "location could not be loaded",
};

function gapKey(g: Gap): string { return `${g.from}-${g.to}`; }

/** Every distinct gap, with the channels it breaks. */
function gapList(channels: Record<Channel, ChannelView>): { gap: Gap; labels: string[] }[] {
  const out = new Map<string, { gap: Gap; labels: string[] }>();
  for (const r of ROWS) {
    const ch = channels[r.channel];
    for (const g of ch.trailing ? [...ch.gaps, ch.trailing] : ch.gaps) {
      const k = gapKey(g);
      if (!out.has(k)) out.set(k, { gap: g, labels: [] });
      out.get(k)!.labels.push(r.label);
    }
  }
  return [...out.values()].sort((a, b) => a.gap.from - b.gap.from);
}

/** The union of sample times on screen, oldest first (hover moves over these). */
function sampleTimes(channels: Record<Channel, ChannelView>): number[] {
  const ts = new Set<number>();
  for (const r of ROWS) for (const run of channels[r.channel].runs) for (const s of run) ts.add(s.t);
  return [...ts].sort((a, b) => a - b);
}

function valueAt(ch: ChannelView, t: number): number | null {
  for (const run of ch.runs) {
    if (!run.length || run[0].t > t || run[run.length - 1].t < t) continue;
    const hit = run.find((s) => s.t === t);
    if (hit) return hit.value;
  }
  return null;
}

export const CarTelemetryPanel = memo(function CarTelemetryPanel({
  telemetry, driver, ident, playing, hovered, onHover, ghostStatus,
}: {
  telemetry: TelemetryView; driver: number | null; ident: DriverIdentity | undefined; playing: boolean;
  hovered: number | null; onHover: (t: number | null) => void; ghostStatus: GhostView["status"];
}) {
  const [frameRef, width] = useWidth<HTMLDivElement>(420);
  const view = telemetry.view;
  const code = driver == null ? "" : driverCode(ident, driver);
  const times = useMemo(() => (view ? sampleTimes(view.channels) : []), [view]);
  const gaps = useMemo(() => (view ? gapList(view.channels) : []), [view]);

  const axisFrom = view ? view.to - TELEMETRY_BACK_MS : 0;
  const narrow = width < NARROW_PX;
  const plotX0 = narrow ? 4 : LABEL_W;
  const plotW = Math.max(40, narrow ? width - 8 : width - LABEL_W - VALUE_W);
  const head = narrow ? HEAD_H : 0;
  const x = useCallback((t: number) => plotX0 + ((t - axisFrom) / TELEMETRY_BACK_MS) * plotW, [plotX0, axisFrom, plotW]);

  const nearest = useCallback((px: number): number | null => {
    if (!times.length) return null;
    const t = axisFrom + ((px - plotX0) / plotW) * TELEMETRY_BACK_MS;
    let best = times[0];
    for (const s of times) if (Math.abs(s - t) < Math.abs(best - t)) best = s;
    return best;
  }, [times, axisFrom, plotX0, plotW]);

  const onMove = useCallback((e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const t = nearest(e.clientX - box.left);
    if (t != null && t !== hovered) onHover(t);
  }, [nearest, hovered, onHover]);

  const onKey = useCallback((e: KeyboardEvent<SVGSVGElement>) => {
    if (!times.length) return;
    const i = hovered == null ? -1 : times.indexOf(hovered);
    let next: number | null;
    if (e.key === "ArrowLeft") next = times[i < 0 ? times.length - 1 : Math.max(0, i - 1)];
    else if (e.key === "ArrowRight") next = times[i < 0 ? times.length - 1 : Math.min(times.length - 1, i + 1)];
    else if (e.key === "Home") next = times[0];
    else if (e.key === "End") next = times[times.length - 1];
    else if (e.key === "Escape") next = null;
    else return;
    e.preventDefault();
    e.stopPropagation();
    onHover(next);
  }, [times, hovered, onHover]);

  const meta = driver == null ? null : (
    <>
      <span className="cc-mono">{code}</span>
      {view && times.length > 0 && <span>samples to {fmtClockTenths(times[times.length - 1])}</span>}
      {telemetry.dataSource && <span className="ct-source">{telemetry.dataSource}</span>}
    </>
  );

  let body;
  if (driver == null || telemetry.status === "idle") {
    body = <EmptyState title="Select a driver to see car telemetry" why="Pick a driver in the timing tower or on the map." />;
  } else if (telemetry.status === "unavailable") {
    body = telemetry.reason === "LIVE"
      ? <EmptyState title="Car telemetry unavailable" why="This panel replays stored or recorded sessions; a running live session is not replayed here." />
      : <EmptyState title="No car telemetry" why={`No stored car telemetry for ${code} in this session.`} />;
  } else if (telemetry.status === "error") {
    body = <ErrorState title="Car telemetry could not be loaded" message={telemetry.error?.message ?? "Unexpected error."}
                       onRetry={telemetry.retry} />;
  } else if (!view) {
    body = <div className="ct-skeleton" aria-busy="true" aria-label="Loading car telemetry" />;
  } else if (!times.length) {
    body = <EmptyState title="No car samples in this minute"
                       why={`No stored car sample for ${code} in the 60 s before ${fmtClockTenths(view.to)}.`} />;
  } else {
    const height = ROWS.length * (head + ROW_H + ROW_GAP) + AXIS_H;
    // a hovered sample outside the shown minute is not read out (it would read as missing)
    const hov = hovered != null && hovered <= view.to && hovered >= view.from ? hovered : null;
    const hx = hov != null ? x(hov) : null;
    body = (
      <>
        <svg className="ct-chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} tabIndex={0}
             role="group" aria-label={`Telemetry chart, ${code}, 60 s to ${fmtClockTenths(view.to)}. Arrow keys step through samples, Escape clears.`}
             onPointerMove={onMove} onPointerLeave={() => onHover(null)} onKeyDown={onKey}>
          <defs>
            <marker id="ct-dot" viewBox="-2 -2 4 4" markerWidth="4" markerHeight="4" markerUnits="userSpaceOnUse">
              <circle r="1.5" className="ct-dot" />
            </marker>
          </defs>
          {ROWS.map((r, k) => {
            const ch = view.channels[r.channel];
            const top = k * (head + ROW_H + ROW_GAP);
            const plotTop = top + head;
            let max = r.max;
            for (const run of ch.runs) for (const s of run) if (s.value > max) max = s.value;
            const y = (v: number) => plotTop + ROW_H - 3 - (v / max) * (ROW_H - 6);
            const pts = (run: Sample[]) => run.map((s) => `${x(s.t).toFixed(1)},${y(s.value).toFixed(1)}`).join(" ");
            const latest = ch.latest;
            const headY = narrow ? top + 12 : top + 15;
            return (
              <g key={r.channel} className={`ct-row ct-${r.channel}`} role="group"
                 aria-label={ch.trailing && latest
                   ? `${r.label}, no sample in the last 2 s (last ${r.format(latest.value)} at ${fmtClockTenths(latest.t)})`
                   : `${r.label}, latest ${latest ? r.format(latest.value) : "no sample"}`}>
                <rect className="ct-band" x={plotX0} y={plotTop} width={plotW} height={ROW_H} />
                <text className="ct-label" x={4} y={headY}>
                  {r.label}{narrow && r.unit && <tspan className="ct-unit">{`  ${r.unit}`}</tspan>}
                </text>
                {!narrow && r.unit && <text className="ct-unit" x={4} y={top + 29}>{r.unit}</text>}
                {(ch.trailing ? [...ch.gaps, ch.trailing] : ch.gaps).map((g) => (
                  <rect key={gapKey(g)} className="ct-gap" x={x(g.from)} y={plotTop} width={Math.max(1, x(g.to) - x(g.from))} height={ROW_H}>
                    <title>{`No samples ${fmtClockTenths(g.from)}–${fmtClockTenths(g.to)}`}</title>
                  </rect>
                ))}
                {ch.runs.map((run) => (run.length > 1 ? (
                  <polyline key={run[0].t} className="ct-line" points={pts(run)} data-t={run[run.length - 1].t}
                            markerStart="url(#ct-dot)" markerMid="url(#ct-dot)" markerEnd="url(#ct-dot)" />
                ) : (
                  <circle key={run[0].t} className="ct-single" cx={x(run[0].t)} cy={y(run[0].value)} r={1.8} data-t={run[0].t} />
                )))}
                {narrow && <line className="ct-cursor" x1={plotX0 + plotW} x2={plotX0 + plotW} y1={plotTop} y2={plotTop + ROW_H} />}
                <text className="ct-value" x={width - (narrow ? 8 : 4)} y={narrow ? headY : top + 23} textAnchor="end"
                      data-testid={`latest-${r.channel}`}>
                  {latest && !ch.trailing ? r.format(latest.value) : "—"}
                </text>
              </g>
            );
          })}
          {!narrow && <line className="ct-cursor" x1={plotX0 + plotW} x2={plotX0 + plotW} y1={0} y2={height - AXIS_H} />}
          {hx != null && <line className="ct-hover" x1={hx} x2={hx} y1={0} y2={height - AXIS_H} data-t={hov!} />}
          <text className="ct-axis" x={plotX0} y={height - 4}>{fmtClockTenths(axisFrom)}</text>
          <text className="ct-axis" x={plotX0 + plotW} y={height - 4} textAnchor="end">cursor {fmtClockTenths(view.to)}</text>
        </svg>
        <p className="ct-drs">
          {view.channels.drs.available
            ? "DRS: raw codes present; their meaning is not verified in this data"
            : "DRS: not in this data (every sample in this window is null)"}
        </p>
        {gaps.length > 0 && (
          <ul className="ct-gaps">
            {gaps.map(({ gap, labels }) => (
              <li key={gapKey(gap)}><span className="ct-gap-ch">{labels.join(", ")}</span>{" "}
                <span>{`No samples ${fmtClockTenths(gap.from)}–${fmtClockTenths(gap.to)}`}</span></li>
            ))}
          </ul>
        )}
        <p className="ct-readout cc-mono" role="status" aria-label="Hovered sample" aria-live="polite">
          {hov != null ? [
            fmtClockTenths(hov),
            ...ROWS.map((r) => {
              const v = valueAt(view.channels[r.channel], hov);
              return v == null ? `${r.label.toLowerCase()} no sample` : r.format(v);
            }),
            GHOST_WORDS[ghostStatus],
          ].filter(Boolean).join(" · ") : "Hover or use the arrow keys to read one stored sample."}
        </p>
        <p className="ct-caption">
          Stored samples up to the cursor; lines join samples and nothing between them is measured.
          A gap over 2 s is never joined.
        </p>
        {!playing && (
          <div className="cc-sr">
            <table aria-label={`Car telemetry samples, ${code}`}>
              <thead><tr><th>time</th>{ROWS.map((r) => <th key={r.channel}>{r.label}</th>)}</tr></thead>
              <tbody>
                {times.map((t) => (
                  <tr key={t}>
                    <td>{fmtClockTenths(t)}</td>
                    {ROWS.map((r) => {
                      const v = valueAt(view.channels[r.channel], t);
                      return <td key={r.channel}>{v == null ? "no sample" : r.format(v)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </>
    );
  }

  return (
    <Panel id="cc-telemetry" title="Car telemetry" className="cc-telemetry" meta={meta}>
      <div className="ct-frame"><div ref={frameRef} className="ct-measure">{body}</div></div>
    </Panel>
  );
});
