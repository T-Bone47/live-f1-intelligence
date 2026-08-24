/** Consolidated panels: pace, battles, weather, RC feed, strategy, driver focus.
 *  All data from backend — frontend renders only. */

import { useEffect, useState } from "react";
import { apiGet, useSessionState } from "../../state/store";
import { Panel, TyreChip, ConfidenceBadge, Metric } from "../shared";
import { UNAVAILABLE } from "../../logic/format";

// ── Pace ────────────────────────────────────────────────────────────────

export function PacePanel({ driver }: { driver: number | null }) {
  const st = useSessionState();
  const rows: any[] = st.snapshot?.leaderboard ?? [];
  const row = rows.find(r => r.driver_number === driver);
  return (
    <Panel title="PACE">
      {!driver ? <p className="dim">SELECT DRIVER</p> : (
        <div className="metric-grid">
          <Metric label="ROLLING 5" value={row?.rolling5_s != null ? `${row.rolling5_s.toFixed(3)}s` : UNAVAILABLE} />
          <Metric label="TREND"
                  value={row?.pace_trend_s_per_lap != null
                    ? `${row.pace_trend_s_per_lap > 0 ? "+" : ""}${row.pace_trend_s_per_lap.toFixed(3)} s/lap`
                    : UNAVAILABLE} />
          <Metric label="BEST" value={row?.personal_best_s != null ? `${row.personal_best_s.toFixed(3)}s` : UNAVAILABLE} />
        </div>
      )}
    </Panel>
  );
}

// ── Battles ─────────────────────────────────────────────────────────────

export function BattleRadar() {
  const st = useSessionState();
  const battles = st.snapshot?.active_battles ?? [];
  if (!battles.length) return (
    <Panel title="BATTLES"><p className="dim">NO ACTIVE BATTLES</p></Panel>
  );
  return (
    <Panel title="BATTLE RADAR">
      {battles.slice(0, 5).map((b: any, i: number) => (
        <div key={i} className={`battle-item ${i === 0 ? "primary-battle" : ""}`}>
          <span className="mono">#{b.behind} {"\u2192"} #{b.ahead}</span>
          <span className={`battle-state-badge ${b.state?.toLowerCase()}`}>
            {b.state?.replace(/_/g, " ") ?? ""}
          </span>
          {b.last_gap_s != null && (
            <span className="battle-gap mono">{b.last_gap_s.toFixed(2)}s</span>
          )}
        </div>
      ))}
    </Panel>
  );
}

// ── Weather ─────────────────────────────────────────────────────────────

export function WeatherStrip() {
  const st = useSessionState();
  const w = st.snapshot?.weather ?? {};
  return (
    <div className="weather-strip" role="status" aria-label="Weather conditions">
      {[
        ["AIR", w.air_temp_c, "\u00B0C"],
        ["TRACK", w.track_temp_c, "\u00B0C"],
        ["HUMIDITY", w.humidity_pct, "%"],
      ].map(([label, val, unit]) => (
        <span key={String(label)} className="wx-item">
          <span className="dim">{label}</span>
          <span className="mono">{val != null ? `${val}${unit}` : UNAVAILABLE}</span>
        </span>
      ))}
      <span className="wx-item">
        <span className="dim">RAIN</span>
        <span className="mono">{w.rainfall == null ? UNAVAILABLE : w.rainfall ? "YES" : "NO"}</span>
      </span>
    </div>
  );
}

// ── Race Control Feed ──────────────────────────────────────────────────

export function RCFeed() {
  const st = useSessionState();
  const events = [...(st.snapshot?.recent_events ?? [])]
    .filter((e: any) =>
      /rcm|RED_FLAG|SAFETY_CAR|VSC|SESSION_STATE|FASTEST_LAP/.test(e.event_type ?? ""))
    .slice(-12).reverse();

  return (
    <Panel title="RACE CONTROL" className="rc-panel">
      {events.length === 0 ? (
        <p className="dim">NO RACE CONTROL EVENTS</p>
      ) : (
        <ul className="rc-feed" aria-live="polite">
          {events.map((e: any, i: number) => (
            <li key={e.event_key || i}>
              <span className="mono dim">{String(e.timestamp).slice(11, 19)}</span>
              <strong>{(e.metrics?.message ?? e.event_type).slice(0, 60)}</strong>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

// ── Strategy Board ────────────────────────────────────────────────────

export function StrategyBoard() {
  const st = useSessionState();
  const [candidates, setCandidates] = useState<any[]>([]);
  const sessionId = st.snapshot?.session_id;

  useEffect(() => {
    if (!sessionId) return;
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/strategy/candidates`)
      .then(d => { if (alive) setCandidates(d.candidates ?? []); })
      .catch(() => {});
    return () => { alive = false; };
  }, [sessionId, Math.floor((st.seq ?? 0) / 300)]);

  return (
    <Panel title="STRATEGY BOARD">
      <div className="strategy-note dim">ANALYSIS ONLY \u2014 NOT A RECOMMENDATION</div>
      {candidates.length === 0 ? (
        <p className="dim">INSUFFICIENT DATA</p>
      ) : (
        <table className="strategy-table">
          <thead><tr><th>#</th><th>STRATEGY</th><th>STOPS</th><th>EST TIME</th><th>CONF</th></tr></thead>
          <tbody>
            {candidates.map((c: any) => (
              <tr key={c.strategy_rank}>
                <td>{c.strategy_rank}</td>
                <td title={(c.assumptions ?? []).join(" \u00B7 ")}>{c.name.replace(/_/g, " ")}</td>
                <td>{c.stops}</td>
                <td className="mono">{c.estimated_total_s != null
                  ? `${Math.floor(c.estimated_total_s / 60)}:${(c.estimated_total_s % 60).toFixed(1).padStart(4, "0")}` : UNAVAILABLE}</td>
                <td><ConfidenceBadge level={c.confidence} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

// ── Circuit fallback ──────────────────────────────────────────────────

export function CircuitFallback() {
  const st = useSessionState();
  const rows = st.snapshot?.leaderboard ?? [];
  return (
    <Panel title="CIRCUIT">
      <p className="dim">Circuit geometry unavailable. Showing live order.</p>
      <div className="pos-strip">
        {rows.map((r: any) => (
          <span key={r.driver_number} className="pos-dot">
            P{r.position} #{r.driver_number}
          </span>
        ))}
      </div>
    </Panel>
  );
}
