/** Synchronized telemetry lab: speed/throttle/brake/gear traces sharing one
 *  X-axis, with a crosshair cursor. Data comes from REST LTTB-downsampled
 *  series — no client-side analysis. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, useSessionState } from "../../state/store";
import { Panel } from "../shared";

interface SeriesPoint { ts: string; value: number }
type SeriesMap = Record<string, SeriesPoint[]>;

const TRACE_DEFS = [
  { key: "speed", label: "SPEED", unit: "km/h", color: "var(--info)", min: 0 },
  { key: "throttle", label: "THROTTLE", unit: "%", color: "var(--sector-green)", min: 0 },
  { key: "brake", label: "BRAKE", unit: "%", color: "var(--live)", min: 0 },
] as const;

function toPath(pts: [number, number][], w: number, h: number,
                min: number, max: number): string {
  if (pts.length < 2) return "";
  const span = max - min || 1;
  const dx = pts[pts.length - 1][0] - pts[0][0] || 1;
  return pts.map(([t, v], i) => {
    const x = ((t - pts[0][0]) / dx) * w;
    const y = h - ((v - min) / span) * (h - 4) - 2;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

export function TelemetryLab({ driverA, driverB }: {
  driverA: number | null; driverB: number | null;
}) {
  const st = useSessionState();
  const sessionId = st.snapshot?.session_id as string | undefined;
  const [seriesA, setSeriesA] = useState<SeriesMap>({});
  const [seriesB, setSeriesB] = useState<SeriesMap>({});
  const [cursorX, setCursorX] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!sessionId || !driverA) return;
    const ac = new AbortController();
    setLoading(true);
    const qs = "frequency=MEDIUM&fields=speed,throttle,brake,gear,rpm";
    Promise.all([
      apiGet(`/sessions/${encodeURIComponent(sessionId)}/telemetry/${driverA}?${qs}`).catch(() => null),
      driverB ? apiGet(`/sessions/${encodeURIComponent(sessionId)}/telemetry/${driverB}?${qs}`).catch(() => null) : null,
    ]).then(([a, b]) => {
      if (!ac.signal.aborted) {
        setSeriesA(a?.series ?? {});
        setSeriesB(b?.series ?? {});
        setLoading(false);
      }
    });
    return () => ac.abort();
  }, [sessionId, driverA, driverB, Math.floor((st.seq ?? 0) / 500)]);

  const allSpeed = useMemo(() => {
    const a = seriesA.speed ?? []; const b = seriesB.speed ?? [];
    return [...a, ...b].map(p => p.value);
  }, [seriesA, seriesB]);

  const speedMin = Math.min(...allSpeed, 0);
  const speedMax = Math.max(...allSpeed, 300);

  const onCursor = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    setCursorX(((e.clientX - rect.left) / rect.width) * 100);
  }, []);

  const W = 600, H = 100;

  function traceSvg(key: string, color: string, label: string,
                    dataA: SeriesPoint[] | undefined, dataB?: SeriesPoint[],
                    fixedMin2?: number, fixedMax?: number) {
    const ptsA: [number, number][] = (dataA ?? []).map((p, i) => [i, p.value]);
    const ptsB: [number, number][] = (dataB ?? []).map((p, i) => [i, p.value]);
    const all = [...ptsA.map(p => p[1]), ...ptsB.map(p => p[1])];
    const min = fixedMin2 ?? Math.min(...all, 0);
    const max = fixedMax ?? Math.max(...all, 1);
    const hasData = ptsA.length > 0;

    if (!hasData) return (
      <div className="trace-block" key={key}>
        <span className="trace-label dim">{label} · NO DATA</span>
      </div>
    );

    return (
      <div className="trace-block" key={key}>
        <span className="trace-label" style={{ color }}>{label}</span>
        <svg ref={key === "speed" ? svgRef : undefined}
             viewBox={`0 0 ${W} ${H}`} className="trace-svg"
             onMouseMove={onCursor} onMouseLeave={() => setCursorX(null)}
             role="img" aria-label={`${label} trace`}>
          <line x1="0" y1={H - 2} x2={W} y2={H - 2} stroke="var(--border)" strokeWidth="0.5" />
          {cursorX != null && (
            <line x1={(cursorX / 100) * W} y1="0" x2={(cursorX / 100) * W} y2={H}
                  stroke="var(--text-muted)" strokeWidth="0.5" strokeDasharray="3,3" />
          )}
          <path d={toPath(ptsA, W, H, min, max)} fill="none"
                stroke="var(--driver-a)" strokeWidth="1.4" />
          {ptsB.length > 0 && (
            <path d={toPath(ptsB, W, H, min, max)} fill="none"
                  stroke="var(--driver-b)" strokeWidth="1.4"
                  strokeDasharray="4,2" opacity={0.85} />
          )}
        </svg>
      </div>
    );
  }

  if (!driverA) {
    return <Panel title="TELEMETRY LAB"><p className="dim">SELECT A DRIVER</p></Panel>;
  }

  return (
    <Panel title={`TELEMETRY LAB — #${driverA}${driverB ? ` vs #${driverB}` : ""}`}
           className="telemetry-lab">
      {loading ? (
        <p className="dim">LOADING TELEMETRY…</p>
      ) : Object.keys(seriesA).length === 0 ? (
        <p className="dim">NO TELEMETRY AVAILABLE FOR THIS SESSION</p>
      ) : (
        <>
          {traceSvg("speed", "var(--info)", `SPEED km/h`, seriesA.speed, driverB ? seriesB.speed : undefined)}
          {traceSvg("throttle", "var(--sector-green)", "THROTTLE %", seriesA.throttle, driverB ? seriesB.throttle : undefined)}
          {traceSvg("brake", "var(--live)", "BRAKE %", seriesA.brake, driverB ? seriesB.brake : undefined)}
          <div className="legend-row">
            <span><span className="lg-dot" style={{ background: "var(--driver-a)" }} /> A #{driverA}</span>
            {driverB && <span><span className="lg-dot" style={{ background: "var(--driver-b)" }} /> B #{driverB}</span>}
            <span className="dim ml-auto">ALIGNMENT: TIME</span>
          </div>
        </>
      )}
    </Panel>
  );
}
