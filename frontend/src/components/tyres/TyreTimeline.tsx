import { useEffect, useMemo, useState } from "react";
import { apiGet, useSessionState } from "../../state/store";
import { Panel, TyreChip, ConfidenceBadge, Metric } from "../shared";
import { UNAVAILABLE } from "../../logic/format";

const COMPOUND_COLOR: Record<string, string> = {
  SOFT: "var(--tyre-soft)", MEDIUM: "var(--tyre-medium)",
  HARD: "#c0c0c8", INTERMEDIATE: "var(--sector-green)", WET: "var(--info)",
};

interface StintRow {
  stint_number: number; compound: string; lap_start: number | null;
  lap_end: number | null; estimated_degradation: number | null;
  base_pace_s: number | null; r_squared: number | null;
  n_samples: number | null; confidence: string;
}

/** Gantt-style stint timeline for all drivers. */
export function TyreStrategyTimeline({ selectedDriver }: { selectedDriver: number | null }) {
  const st = useSessionState();
  const intel = st.snapshot?.intelligence as any;
  const tyres = (intel?.tyres_2 ?? {}) as Record<string, any[]>;
  const entries = Object.entries(tyres).sort(([a], [b]) => Number(a) - Number(b));

  const maxEnd = entries.reduce((mx, [, ss]) =>
    Math.max(mx, ...ss.map((s: any) => s.lap_end ?? 0)), 1);

  return (
    <Panel title="TYRE STRATEGY TIMELINE" className="tyre-timeline">
      {entries.length === 0 ? (
        <p className="dim">STINT DATA UNAVAILABLE</p>
      ) : (
        <div className="tt-scroll">
          {entries.map(([dn, stints]) => (
            <div key={dn}
                 className={`stint-row ${Number(selectedDriver) === Number(dn) ? "sel" : ""}`}>
              <span className="stint-drv mono text-xs">#{dn}</span>
              <div className="stint-track">
                {(stints as any[]).map((s: any, i: number) => {
                  const w = ((s.lap_end - s.lap_start) / maxEnd) * 100;
                  const off = (s.lap_start / maxEnd) * 100;
                  return (
                    <div key={i} className="stint-seg"
                         style={{ left: `${off}%`, width: `${Math.max(w, 1.5)}%`,
                                  background: COMPOUND_COLOR[s.compound] ?? "var(--text-muted)" }}
                         title={`${dn} ${s.compound} L${s.lap_start}-${s.lap_end}`}>
                      {w > 4 && <span className="stint-compound-label">{(s.compound ?? "?")[0]}</span>}
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
  const sessionId = st.snapshot?.session_id;

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
      <Metric label="EST. DEGRADATION"
              value={d.rate_s_per_lap != null
                ? `${d.rate_s_per_lap > 0 ? "+" : ""}${d.rate_s_per_lap.toFixed(3)} s/lap` : UNAVAILABLE} />
      <Metric label="BASE PACE" value={d.base_pace_s != null ? `${d.base_pace_s.toFixed(3)}s` : UNAVAILABLE} />
      <Metric label="SAMPLES" value={d.sample_count} />
      <ConfidenceBadge level={d.confidence} />
      <p className="est-tag dim">ESTIMATED DEGRADATION — not official data</p>
    </div>
  );
}
