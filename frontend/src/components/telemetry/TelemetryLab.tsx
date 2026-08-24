/**
 * TelemetryLab 2.0 — Engineering-grade telemetry visualization
 * Features: speed/throttle/brake/gear traces, driver comparison,
 * synchronized crosshair, sector boundary markers, dark grid background
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSessionState, useDriverSelection, apiGet } from "../../state/store";
import { Panel, TyreChip } from "../shared";
import { UNAVAILABLE } from "../../logic/format";

type TraceType = "SPEED" | "THROTTLE" | "BRAKE" | "GEAR";
const ALL_TRACES: TraceType[] = ["SPEED", "THROTTLE", "BRAKE", "GEAR"];

interface TraceSample { distance_m?: number; time_s?: number; value: number; }

export function TelemetryLab() {
  const st = useSessionState();
  const { selectedDriver, comparisonDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const sessionId = snap?.session_id;

  const [activeTraces, setActiveTraces] = useState<Set<TraceType>>(new Set(["SPEED"]));
  const [dataA, setDataA] = useState<any>(null);
  const [dataB, setDataB] = useState<any>(null);
  const [cursorX, setCursorX] = useState<number | null>(null);

  const driverA = selectedDriver ?? snap?.leaderboard?.[0]?.driver_number ?? null;
  const driverB = comparisonDriver;

  // Fetch telemetry for driver A
  useEffect(() => {
    if (!sessionId || !driverA) { setDataA(null); return; }
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/telemetry/${driverA}`)
      .then((d) => { if (alive) setDataA(d); })
      .catch(() => { if (alive) setDataA(null); });
    return () => { alive = false; };
  }, [sessionId, driverA, st.seq]);

  // Fetch telemetry for driver B
  useEffect(() => {
    if (!sessionId || !driverB) { setDataB(null); return; }
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/telemetry/${driverB}`)
      .then((d) => { if (alive) setDataB(d); })
      .catch(() => { if (alive) setDataB(null); });
    return () => { alive = false; };
  }, [sessionId, driverB, st.seq]);

  const toggleTrace = useCallback((t: TraceType) => {
    setActiveTraces((prev) => {
      const next = new Set(prev);
      if (next.has(t)) { if (next.size > 1) next.delete(t); }
      else next.add(t);
      return next;
    });
  }, []);

  const hasData = dataA?.available !== false;

  return (
    <Panel title="TELEMETRY LAB" className="telemetry-lab"
      actions={
        <div className="legend-row">
          {driverA && (
            <span>
              <span className="lg-dot" style={{ background: "var(--driver-a)" }} />
              <span className="mono text-xs">#{driverA}</span>
            </span>
          )}
          {driverB && (
            <span>
              <span className="lg-dot" style={{ background: "var(--driver-b)" }} />
              <span className="mono text-xs">#{driverB}</span>
            </span>
          )}
          <span className="ml-auto" style={{ display: "flex", gap: 2 }}>
            {ALL_TRACES.map((t) => (
              <button key={t} className={`preset-btn ${activeTraces.has(t) ? "active" : ""}`}
                      onClick={() => toggleTrace(t)} style={{ fontSize: "9px", padding: "1px 6px" }}>
                {t}
              </button>
            ))}
          </span>
        </div>
      }>
      {!hasData ? (
        <p className="dim text-sm uppercase" style={{ padding: "var(--sp-4)" }}>
          {driverA ? "NO TELEMETRY AVAILABLE" : "SELECT A DRIVER FOR TELEMETRY"}
        </p>
      ) : (
        <div onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          setCursorX((e.clientX - rect.left) / rect.width);
        }}
        onMouseLeave={() => setCursorX(null)}>
          {activeTraces.has("SPEED") && (
            <TraceChart label="SPEED" unit="km/h"
              samplesA={dataA?.samples?.speed} samplesB={dataB?.samples?.speed}
              yMin={0} yMax={360} height={120} cursorX={cursorX} />
          )}
          {activeTraces.has("THROTTLE") && (
            <TraceChart label="THROTTLE" unit="%"
              samplesA={dataA?.samples?.throttle} samplesB={dataB?.samples?.throttle}
              yMin={0} yMax={100} height={60} cursorX={cursorX} />
          )}
          {activeTraces.has("BRAKE") && (
            <TraceChart label="BRAKE" unit="%"
              samplesA={dataA?.samples?.brake} samplesB={dataB?.samples?.brake}
              yMin={0} yMax={100} height={60} cursorX={cursorX} />
          )}
          {activeTraces.has("GEAR") && (
            <TraceChart label="GEAR" unit=""
              samplesA={dataA?.samples?.gear} samplesB={dataB?.samples?.gear}
              yMin={0} yMax={8} height={40} cursorX={cursorX} step />
          )}
        </div>
      )}
    </Panel>
  );
}

/* ── Trace chart (SVG) ── */
const TraceChart = memo(function TraceChart({
  label, unit, samplesA, samplesB, yMin, yMax, height, cursorX, step,
}: {
  label: string; unit: string;
  samplesA: TraceSample[] | undefined;
  samplesB: TraceSample[] | undefined;
  yMin: number; yMax: number; height: number;
  cursorX: number | null;
  step?: boolean;
}) {
  const W = 800;
  const H = height;
  const pad = { top: 2, bottom: 2, left: 0, right: 0 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const buildPath = useCallback((samples: TraceSample[] | undefined, color: string): string | null => {
    if (!samples || samples.length === 0) return null;
    const pts = samples.map((s, i) => {
      const x = pad.left + (i / (samples.length - 1)) * plotW;
      const y = pad.top + plotH - ((s.value - yMin) / (yMax - yMin)) * plotH;
      return { x, y: Math.max(pad.top, Math.min(pad.top + plotH, y)) };
    });

    if (step) {
      let d = `M${pts[0].x},${pts[0].y}`;
      for (let i = 1; i < pts.length; i++) {
        d += `H${pts[i].x}V${pts[i].y}`;
      }
      return d;
    }

    return pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join("");
  }, [plotW, plotH, yMin, yMax, pad, step]);

  const pathA = buildPath(samplesA, "var(--driver-a)");
  const pathB = buildPath(samplesB, "var(--driver-b)");

  // Grid lines
  const gridLines = [];
  const gridCount = step ? yMax : 4;
  for (let i = 0; i <= gridCount; i++) {
    const y = pad.top + (i / gridCount) * plotH;
    gridLines.push(y);
  }

  return (
    <div className="trace-block">
      <span className="trace-label dim">{label}{unit && ` (${unit})`}</span>
      <svg className="trace-svg" viewBox={`0 0 ${W} ${H}`}
           preserveAspectRatio="none" style={{ height }}>
        {/* Grid */}
        {gridLines.map((y, i) => (
          <line key={i} x1={pad.left} x2={W - pad.right} y1={y} y2={y}
                stroke="var(--border)" strokeWidth="0.5" />
        ))}

        {/* Traces */}
        {pathA && (
          <path d={pathA} fill="none" stroke="var(--driver-a)"
                strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        )}
        {pathB && (
          <path d={pathB} fill="none" stroke="var(--driver-b)"
                strokeWidth="1.5" vectorEffect="non-scaling-stroke" opacity={0.8} />
        )}

        {/* Cursor */}
        {cursorX != null && (
          <line x1={cursorX * W} x2={cursorX * W} y1={0} y2={H}
                stroke="var(--text-muted)" strokeWidth="1" strokeDasharray="3,3"
                vectorEffect="non-scaling-stroke" />
        )}
      </svg>
    </div>
  );
});
