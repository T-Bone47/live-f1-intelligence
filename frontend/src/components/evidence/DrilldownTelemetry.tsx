/**
 * Telemetry drill-down for one segment — fetched ONLY when the user opens it,
 * through the segment's own telemetry_references (the existing route).
 *
 * The x-axis is time since each driver's own reference start: the two laps
 * are NOT distance-aligned here, and the panel says so. Samples are drawn as
 * stored (RAW, markers visible); the readout shows the nearest stored sample,
 * never an interpolated value. All channel charts share one synchronized
 * cursor.
 */

import { memo, useEffect, useMemo, useState, type PointerEvent } from "react";
import type { Segment, TelemetryReference } from "../../evidence/types";
import type { EvidenceView } from "../../evidence/viewModel";
import {
  DRILLDOWN_CHANNELS, EvidenceError, fetchTelemetryReference, telemetryUrl,
  type DrilldownChannel, type TelemetryPoint, type TelemetryWindow,
} from "../../evidence/api";
import { fmtClock, UNAVAILABLE } from "../../evidence/format";
import { linear, useElementWidth } from "./chartGeometry";
import { Icon } from "./primitives";

const CHANNEL: Record<DrilldownChannel, { label: string; unit: string; h: number; fixed?: [number, number] }> = {
  speed: { label: "Speed", unit: "km/h", h: 96 },
  throttle: { label: "Throttle", unit: "%", h: 52, fixed: [0, 100] },
  brake: { label: "Brake", unit: "%", h: 40, fixed: [0, 100] },
  gear: { label: "Gear", unit: "", h: 48, fixed: [0, 8] },
  drs: { label: "DRS (raw code)", unit: "", h: 40 },
};

interface Trace { t: number[]; v: number[] }
type Loaded = { a: TelemetryWindow; b: TelemetryWindow; refA: TelemetryReference; refB: TelemetryReference };
type State = { status: "loading" } | { status: "error"; error: EvidenceError } | { status: "ready"; data: Loaded };

const cache = new Map<string, TelemetryWindow>();

async function load(ref: TelemetryReference, signal: AbortSignal): Promise<TelemetryWindow> {
  const key = telemetryUrl(ref);
  const hit = cache.get(key);
  if (hit) return hit;
  const w = await fetchTelemetryReference(ref, signal);
  cache.set(key, w);
  return w;
}

function toTrace(points: TelemetryPoint[], start: string): Trace {
  const t0 = Date.parse(start);
  const t: number[] = [], v: number[] = [];
  for (const p of points) { const ms = Date.parse(p.ts); if (Number.isFinite(ms)) { t.push((ms - t0) / 1000); v.push(p.value); } }
  return { t, v };
}

function nearest(tr: Trace, at: number): number | null {
  if (tr.t.length === 0) return null;
  let best = 0;
  for (let i = 1; i < tr.t.length; i++) if (Math.abs(tr.t[i] - at) < Math.abs(tr.t[best] - at)) best = i;
  return tr.v[best];
}

export function DrilldownTelemetry({ view, segment, onClose }: { view: EvidenceView; segment: Segment; onClose: () => void }) {
  const refA = segment.telemetry_references.find((r) => r.driver_number === view.a);
  const refB = segment.telemetry_references.find((r) => r.driver_number === view.b);
  const [state, setState] = useState<State>({ status: "loading" });
  const [cursor, setCursor] = useState<number | null>(null);

  useEffect(() => {
    if (!refA || !refB) { setState({ status: "error", error: new EvidenceError("unsupported", "This segment has no telemetry reference for both drivers.", null) }); return; }
    const ctrl = new AbortController();
    setState({ status: "loading" });
    Promise.all([load(refA, ctrl.signal), load(refB, ctrl.signal)])
      .then(([a, b]) => { if (!ctrl.signal.aborted) setState({ status: "ready", data: { a, b, refA, refB } }); })
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        setState({ status: "error", error: e instanceof EvidenceError ? e : new EvidenceError("unexpected", String(e?.message ?? e), null) });
      });
    return () => ctrl.abort();
  }, [refA, refB]);

  return (
    <section id="ewb-drilldown" className="ewb-section ewb-drill" aria-labelledby="ewb-drill-title" aria-busy={state.status === "loading" || undefined}>
      <header className="ewb-section-head">
        <div>
          <p className="ewb-eyebrow">Telemetry drill-down · stored samples (RAW)</p>
          <h2 id="ewb-drill-title" className="ewb-section-title">{segment.label} — #{view.a} vs #{view.b}</h2>
        </div>
        <button type="button" className="ewb-btn ewb-btn-icon" aria-label="Close telemetry drill-down" onClick={onClose}><Icon name="x" /></button>
      </header>
      <p className="ewb-drill-note">
        <Icon name="info" /> Time axis: seconds since each driver's own segment reference start. <strong>Not distance-aligned</strong> —
        compare shapes, not x positions. The aligned comparison is the evidence above.
      </p>
      {state.status === "loading" && <div className="ewb-skel ewb-skel-drill" role="status" aria-label="Loading telemetry" />}
      {state.status === "error" && (
        <div className="ewb-state-box is-error" role="alert"><Icon name="alert" /><div>
          <p className="ewb-state-title">Telemetry unavailable</p><p className="ewb-state-msg"><code>{state.error.message}</code></p>
        </div></div>
      )}
      {state.status === "ready" && <Traces view={view} data={state.data} cursor={cursor} setCursor={setCursor} />}
    </section>
  );
}

const Traces = memo(function Traces({ view, data, cursor, setCursor }: {
  view: EvidenceView; data: Loaded; cursor: number | null; setCursor: (t: number | null) => void;
}) {
  const { ref, width } = useElementWidth<HTMLDivElement>();
  const traces = useMemo(() => Object.fromEntries(DRILLDOWN_CHANNELS.map((c) => [c, {
    a: toTrace(data.a.series[c], data.refA.start), b: toTrace(data.b.series[c], data.refB.start),
  }])) as Record<DrilldownChannel, { a: Trace; b: Trace }>, [data]);
  const tMax = Math.max(0.1, ...DRILLDOWN_CHANNELS.flatMap((c) => [...traces[c].a.t, ...traces[c].b.t]));
  const m = { l: 44, r: 10 };
  const sx = linear(0, tMax, m.l, Math.max(m.l + 40, width - m.r));
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setCursor(Math.max(0, Math.min(tMax, ((e.clientX - r.left - m.l) / Math.max(1, r.width - m.l - m.r)) * tMax)));
  };

  return (
    <div ref={ref} className="ewb-traces">
      <p className="ewb-small ewb-muted">
        #{view.a}: {fmtClock(data.refA.start)} → {fmtClock(data.refA.end)} · #{view.b}: {fmtClock(data.refB.start)} → {fmtClock(data.refB.end)} ·
        provenance class {data.a.provenanceClass ?? UNAVAILABLE}/{data.b.provenanceClass ?? UNAVAILABLE}
      </p>
      {DRILLDOWN_CHANNELS.map((c) => {
        const cfg = CHANNEL[c], tr = traces[c];
        const all = [...tr.a.v, ...tr.b.v];
        if (all.length === 0) return <p key={c} className="ewb-muted ewb-small">{cfg.label}: no samples in this window.</p>;
        const lo = cfg.fixed ? cfg.fixed[0] : Math.min(...all), hi = cfg.fixed ? cfg.fixed[1] : Math.max(...all);
        const pad = cfg.fixed ? 0 : Math.max(1, (hi - lo) * 0.1);
        const sy = linear(lo - pad, hi + pad, cfg.h - 4, 4);
        const path = (t: Trace) => t.t.map((x, i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(t.v[i]).toFixed(1)}`).join("");
        const va = cursor == null ? null : nearest(tr.a, cursor), vb = cursor == null ? null : nearest(tr.b, cursor);
        return (
          <div key={c} className="ewb-trace">
            <div className="ewb-trace-head">
              <span className="ewb-label">{cfg.label}{cfg.unit && ` (${cfg.unit})`}</span>
              <span className="ewb-mono ewb-small">
                {cursor == null ? "hover for nearest samples" : <>t {cursor.toFixed(2)} s · <span className="ewb-tone-a">#{view.a} {va ?? UNAVAILABLE}</span> · <span className="ewb-tone-b">#{view.b} {vb ?? UNAVAILABLE}</span></>}
              </span>
            </div>
            <svg width={width} height={cfg.h} className="ewb-trace-svg" onPointerMove={onMove} onPointerLeave={() => setCursor(null)}
                 role="img" aria-label={`${cfg.label}: #${view.a} ${tr.a.v.length} samples, #${view.b} ${tr.b.v.length} samples`}>
              <line x1={m.l} x2={width - m.r} y1={cfg.h - 4} y2={cfg.h - 4} className="ewb-gridline" />
              <text x={m.l - 4} y={10} textAnchor="end" className="ewb-tick">{Math.round(hi)}</text>
              <text x={m.l - 4} y={cfg.h - 4} textAnchor="end" className="ewb-tick">{Math.round(lo)}</text>
              <path d={path(tr.b)} className="ewb-trace-line is-b" />
              <path d={path(tr.a)} className="ewb-trace-line is-a" />
              {tr.a.t.map((x, i) => <circle key={`a${i}`} cx={sx(x)} cy={sy(tr.a.v[i])} r={1.6} className="ewb-trace-pt is-a" />)}
              {tr.b.t.map((x, i) => <rect key={`b${i}`} x={sx(x) - 1.4} y={sy(tr.b.v[i]) - 1.4} width={2.8} height={2.8} className="ewb-trace-pt is-b" />)}
              {cursor != null && <line x1={sx(cursor)} x2={sx(cursor)} y1={0} y2={cfg.h} className="ewb-crosshair" />}
            </svg>
          </div>
        );
      })}
      <p className="ewb-small ewb-muted ewb-trace-axis">0 s → {tMax.toFixed(1)} s since each reference start · A solid/round markers · B dashed/square markers</p>
    </div>
  );
});
