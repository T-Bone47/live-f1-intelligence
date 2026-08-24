/**
 * Tyre Intelligence 2.0 — Gantt timeline, degradation detail, performance comparison
 */

import { useEffect, useMemo, useState } from "react";
import { apiGet, useSessionState, useDriverSelection, useIntelligence } from "../../state/store";
import { Panel, TyreChip, ConfidenceBadge, Metric, ProvenanceBadge } from "../shared";
import { UNAVAILABLE, fmtSec, degradationText } from "../../logic/format";

const COMPOUND_COLOR: Record<string, string> = {
  SOFT: "var(--tyre-soft)", MEDIUM: "var(--tyre-medium)",
  HARD: "var(--tyre-hard)", INTERMEDIATE: "var(--tyre-inter)", WET: "var(--tyre-wet)",
};

/** Gantt-style stint timeline for all drivers. */
export function TyreStrategyTimeline() {
  const st = useSessionState();
  const { selectedDriver } = useDriverSelection();
  const intel = (st.snapshot as any)?.intelligence as any;
  const tyres = (intel?.tyres_2 ?? {}) as Record<string, any[]>;
  const entries = Object.entries(tyres).sort(([a], [b]) => Number(a) - Number(b));

  const maxEnd = entries.reduce((mx, [, ss]) =>
    Math.max(mx, ...ss.map((s: any) => s.lap_end ?? 0)), 1);

  // Lap markers
  const lapMarkers = useMemo(() => {
    const markers = [];
    const step = maxEnd > 50 ? 10 : maxEnd > 20 ? 5 : 1;
    for (let i = step; i <= maxEnd; i += step) {
      markers.push(i);
    }
    return markers;
  }, [maxEnd]);

  return (
    <Panel title="TYRE STRATEGY TIMELINE" className="tyre-timeline"
      actions={<ProvenanceBadge type="DERIVED" />}>
      {entries.length === 0 ? (
        <p className="dim text-sm uppercase">STINT DATA UNAVAILABLE</p>
      ) : (
        <div className="tt-scroll">
          {/* Lap markers */}
          <div style={{ display: "flex", marginLeft: 40, marginBottom: 2, position: "relative", height: 12 }}>
            {lapMarkers.map((lap) => (
              <span key={lap} className="dim mono" style={{
                position: "absolute", left: `${(lap / maxEnd) * 100}%`, fontSize: 8,
                transform: "translateX(-50%)",
              }}>
                L{lap}
              </span>
            ))}
          </div>

          {entries.map(([dn, stints]) => (
            <div key={dn}
                 className={`stint-row ${Number(selectedDriver) === Number(dn) ? "sel" : ""}`}>
              <span className="stint-drv mono text-xs">#{dn}</span>
              <div className="stint-track">
                {(stints as any[]).map((s: any, i: number) => {
                  const start = s.lap_start ?? 0;
                  const end = s.lap_end ?? start;
                  const w = ((end - start) / maxEnd) * 100;
                  const off = (start / maxEnd) * 100;
                  return (
                    <div key={i} className="stint-seg"
                         style={{
                           left: `${off}%`,
                           width: `${Math.max(w, 1.5)}%`,
                           background: COMPOUND_COLOR[s.compound] ?? "var(--text-muted)",
                         }}
                         title={`#${dn} ${s.compound} L${start}-${end}${
                           s.degradation_rate_s_per_lap != null
                             ? ` deg: +${s.degradation_rate_s_per_lap.toFixed(3)}s/lap`
                             : ""}`}>
                      {w > 5 && (
                        <span className="stint-compound-label">{(s.compound ?? "?")[0]}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

/** Per-driver degradation detail with confidence labeling. */
export function DegradationDetail({ driver }: { driver: number }) {
  const st = useSessionState();
  const [data, setData] = useState<any>(null);
  const sessionId = (st.snapshot as any)?.session_id;

  useEffect(() => {
    if (!sessionId || !driver) { setData(null); return; }
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/tyres/${driver}`)
      .then(d => { if (alive) setData(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [driver, sessionId]);

  if (!data?.available) return null;
  const d = data.degradation;

  return (
    <div className="deg-detail">
      <div className="metric-grid">
        <Metric label="EST. DEGRADATION" provenance="ESTIMATED"
                value={d.rate_s_per_lap != null
                  ? `${d.rate_s_per_lap > 0 ? "+" : ""}${d.rate_s_per_lap.toFixed(3)} s/lap` : UNAVAILABLE} />
        <Metric label="BASE PACE"
                value={d.base_pace_s != null ? `${d.base_pace_s.toFixed(3)}s` : UNAVAILABLE} />
        <Metric label="SAMPLES" value={d.sample_count} />
        <Metric label="CONFIDENCE" value={<ConfidenceBadge level={d.confidence} />} />
      </div>
      <p className="est-tag dim">ESTIMATED DEGRADATION — not official data</p>
    </div>
  );
}

/** Rolling pace comparison for selected drivers */
export function PaceComparison() {
  const st = useSessionState();
  const { selectedDriver, comparisonDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const board: any[] = snap?.leaderboard ?? [];

  const driverA = board.find((r: any) => r.driver_number === selectedDriver);
  const driverB = board.find((r: any) => r.driver_number === comparisonDriver);

  if (!driverA) return null;

  return (
    <Panel title="ROLLING PACE (LAST 5 LAPS)">
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-2)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--driver-a)", flexShrink: 0 }} />
          <span className="mono" style={{ fontWeight: 700, width: 32 }}>#{selectedDriver}</span>
          <span className="mono" style={{ fontWeight: 600, fontSize: "var(--text-md)" }}>
            {driverA.rolling5_s != null ? fmtSec(driverA.rolling5_s) : UNAVAILABLE}
          </span>
          {driverA.pace_trend_s_per_lap != null && (
            <span className={`mono text-xs ${driverA.pace_trend_s_per_lap > 0.05 ? "delta-bad" : driverA.pace_trend_s_per_lap < -0.05 ? "delta-good" : "dim"}`}>
              {driverA.pace_trend_s_per_lap > 0 ? "+" : ""}{driverA.pace_trend_s_per_lap.toFixed(2)}s/lap
            </span>
          )}
        </div>

        {driverB && (
          <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--driver-b)", flexShrink: 0 }} />
            <span className="mono" style={{ fontWeight: 700, width: 32 }}>#{comparisonDriver}</span>
            <span className="mono" style={{ fontWeight: 600, fontSize: "var(--text-md)" }}>
              {driverB.rolling5_s != null ? fmtSec(driverB.rolling5_s) : UNAVAILABLE}
            </span>
            {driverB.pace_trend_s_per_lap != null && (
              <span className={`mono text-xs ${driverB.pace_trend_s_per_lap > 0.05 ? "delta-bad" : driverB.pace_trend_s_per_lap < -0.05 ? "delta-good" : "dim"}`}>
                {driverB.pace_trend_s_per_lap > 0 ? "+" : ""}{driverB.pace_trend_s_per_lap.toFixed(2)}s/lap
              </span>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}
