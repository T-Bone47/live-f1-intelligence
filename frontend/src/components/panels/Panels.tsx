/**
 * Intelligence panels — LIVE F1 INTELLIGENCE
 * BattleRadar, WeatherStrip, StrategyBoard, CircuitMap, RCFeed, RacePicture
 */

import { memo, useState, useEffect, useMemo } from "react";
import { useSessionState, useDriverSelection, apiGet, useIntelligence } from "../../state/store";
import {
  Panel, TyreChip, ConfidenceBadge, Metric, Delta,
  BattleStateBadge, DataFreshness, ProvenanceBadge,
} from "../shared";
import { fmtSec, fmtGap, fmtTime, UNAVAILABLE, trendArrow, eventIcon, fmtLap } from "../../logic/format";

/* ============================================================
   RACE PICTURE — summary bar at the top
   ============================================================ */

export function RacePicture() {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const board: any[] = snap?.leaderboard ?? [];
  const battles: any[] = snap?.active_battles ?? [];
  const fl = snap?.fastest_lap;

  const leader = board[0];
  const closestBattle = battles.length > 0
    ? battles.reduce((a: any, b: any) => (a.last_gap_s ?? 99) < (b.last_gap_s ?? 99) ? a : b)
    : null;

  return (
    <div className="race-picture" role="region" aria-label="Race picture summary">
      <div className="rp-card">
        <span className="rp-label">LEADER</span>
        <span className="rp-value">{leader?.driver_number ?? UNAVAILABLE}</span>
        <span className="rp-sub">
          LAP {leader?.lap_number ?? UNAVAILABLE}
          {leader?.compound && <> · <TyreChip compound={leader.compound} age={leader.tyre_age} /></>}
        </span>
      </div>

      <div className="rp-card">
        <span className="rp-label">CLOSEST BATTLE</span>
        <span className="rp-value">
          {closestBattle
            ? `${closestBattle.behind} → ${closestBattle.ahead}`
            : UNAVAILABLE}
        </span>
        <span className="rp-sub">
          {closestBattle
            ? `${closestBattle.last_gap_s?.toFixed(3) ?? UNAVAILABLE}s`
            : "NO BATTLES"}
        </span>
      </div>

      <div className="rp-card">
        <span className="rp-label">FASTEST LAP</span>
        <span className="rp-value" style={{ color: "var(--sector-purple)" }}>
          {fl?.driver ?? UNAVAILABLE}
        </span>
        <span className="rp-sub">
          {fl?.duration_s != null ? fmtLap(fl.duration_s) : UNAVAILABLE}
          {fl?.at_lap != null && <> · L{fl.at_lap}</>}
        </span>
      </div>

      <div className="rp-card">
        <span className="rp-label">LAP</span>
        <span className="rp-value">{snap?.current_lap ?? UNAVAILABLE}</span>
        <span className="rp-sub">
          {snap?.phase ? snap.phase.replace(/_/g, " ") : UNAVAILABLE}
        </span>
      </div>

      <div className="rp-card">
        <span className="rp-label">WEATHER</span>
        <span className="rp-value">
          {snap?.weather?.air_temp_c != null ? `${snap.weather.air_temp_c.toFixed(0)}°C` : UNAVAILABLE}
        </span>
        <span className="rp-sub">
          {snap?.weather?.track_temp_c != null
            ? `TRK ${snap.weather.track_temp_c.toFixed(0)}°C`
            : ""}
          {snap?.weather?.rain_pct != null && snap.weather.rain_pct > 0
            ? ` · RAIN ${snap.weather.rain_pct}%`
            : ""}
        </span>
      </div>
    </div>
  );
}

/* ============================================================
   BATTLE RADAR — enhanced with gap timeline, states, metrics
   ============================================================ */

export function BattleRadar() {
  const st = useSessionState();
  const { selectedDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const battles: any[] = snap?.active_battles ?? [];

  // Sort: selected driver's battles first, then by gap
  const sorted = useMemo(() => {
    const arr = [...battles];
    arr.sort((a, b) => {
      const aHas = selectedDriver && (a.ahead === selectedDriver || a.behind === selectedDriver);
      const bHas = selectedDriver && (b.ahead === selectedDriver || b.behind === selectedDriver);
      if (aHas && !bHas) return -1;
      if (bHas && !aHas) return 1;
      return (a.last_gap_s ?? 99) - (b.last_gap_s ?? 99);
    });
    return arr;
  }, [battles, selectedDriver]);

  return (
    <Panel title="BATTLE RADAR" className="battle-panel">
      {sorted.length === 0 ? (
        <p className="dim text-sm uppercase">NO ACTIVE BATTLES</p>
      ) : (
        sorted.slice(0, 6).map((b: any, i: number) => (
          <div key={`${b.ahead}-${b.behind}`}
               className={`battle-item ${i === 0 ? "primary-battle" : ""}`}>
            <span className="mono" style={{ fontWeight: 700 }}>{b.behind}</span>
            <span className="dim text-xs">→</span>
            <span className="mono" style={{ fontWeight: 700 }}>{b.ahead}</span>
            <BattleStateBadge state={b.state ?? "APPROACHING"} />
            <span className="battle-gap mono" style={{
              color: (b.last_gap_s ?? 99) < 1 ? "var(--warning)" : "var(--text-primary)"
            }}>
              {b.last_gap_s != null ? `${b.last_gap_s.toFixed(3)}s` : UNAVAILABLE}
            </span>
          </div>
        ))
      )}
    </Panel>
  );
}

/* ============================================================
   WEATHER STRIP — enhanced with trends
   ============================================================ */

export const WeatherStrip = memo(function WeatherStrip() {
  const st = useSessionState();
  const w = (st.snapshot as any)?.weather;

  if (!w) return (
    <div className="weather-strip">
      <span className="dim text-sm uppercase">WEATHER DATA UNAVAILABLE</span>
    </div>
  );

  return (
    <div className="weather-strip" role="region" aria-label="Weather conditions">
      <div className="wx-item">
        <span className="dim">AIR</span>
        <span className="mono">{w.air_temp_c != null ? `${w.air_temp_c.toFixed(1)}°C` : UNAVAILABLE}</span>
      </div>
      <div className="wx-item">
        <span className="dim">TRACK</span>
        <span className="mono">{w.track_temp_c != null ? `${w.track_temp_c.toFixed(1)}°C` : UNAVAILABLE}</span>
      </div>
      <div className="wx-item">
        <span className="dim">HUMIDITY</span>
        <span className="mono">{w.humidity_pct != null ? `${w.humidity_pct}%` : UNAVAILABLE}</span>
      </div>
      <div className="wx-item">
        <span className="dim">WIND</span>
        <span className="mono">
          {w.wind_speed_kph != null ? `${w.wind_speed_kph.toFixed(0)} km/h` : UNAVAILABLE}
          {w.wind_direction_deg != null && <span className="dim"> {windArrow(w.wind_direction_deg)}</span>}
        </span>
      </div>
      {w.rain_pct != null && w.rain_pct > 0 && (
        <div className="wx-item">
          <span className="dim">RAIN</span>
          <span className="mono" style={{ color: "var(--info)" }}>{w.rain_pct}%</span>
        </div>
      )}
    </div>
  );
});

function windArrow(deg: number): string {
  const arrows = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"];
  return arrows[Math.round(deg / 45) % 8];
}

/* ============================================================
   STRATEGY BOARD — narrative format
   ============================================================ */

export function StrategyBoard() {
  const st = useSessionState();
  const { selectedDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const sessionId = snap?.session_id;
  const [strat, setStrat] = useState<any>(null);

  useEffect(() => {
    if (!sessionId) return;
    let alive = true;
    const fetch_ = () => {
      apiGet(`/sessions/${encodeURIComponent(sessionId)}/strategy/candidates`)
        .then((d) => { if (alive) setStrat(d); })
        .catch(() => {});
    };
    fetch_();
    const timer = setInterval(fetch_, 6000);
    return () => { alive = false; clearInterval(timer); };
  }, [sessionId]);

  const candidates = strat?.candidates ?? [];
  const pitLoss = strat?.pit_loss_estimate_s;
  const currentStrat = candidates[0];

  return (
    <Panel title="STRATEGY & STINTS" className="strategy-panel"
      actions={<ProvenanceBadge type="DERIVED" />}>
      {!currentStrat ? (
        <p className="dim text-sm uppercase">STRATEGY DATA UNAVAILABLE</p>
      ) : (
        <div className="strategy-insight">
          <div className="strat-row">
            <span className="strat-label">BASELINE</span>
            <span className="strat-value">{currentStrat.name ?? `${currentStrat.stops}-STOP`}</span>
            <ConfidenceBadge level={currentStrat.confidence ?? "MEDIUM"} />
          </div>

          {pitLoss != null && (
            <div className="strat-row">
              <span className="strat-label">PIT LOSS</span>
              <span className="strat-value mono">{pitLoss.toFixed(1)}s</span>
            </div>
          )}

          {currentStrat.pit_window && (
            <div className="strat-row">
              <span className="strat-label">WINDOW</span>
              <span className="strat-value mono">
                L{currentStrat.pit_window.open} — L{currentStrat.pit_window.close}
              </span>
            </div>
          )}

          {candidates.length > 1 && (
            <>
              <div className="strat-row" style={{ marginTop: "var(--sp-2)" }}>
                <span className="strat-label">ALT</span>
                <span className="strat-value">{candidates[1].name ?? `${candidates[1].stops}-STOP`}</span>
              </div>
              {candidates[1].delta_s != null && (
                <div className="strat-row">
                  <span className="strat-label">DELTA</span>
                  <Delta value={candidates[1].delta_s} suffix="s" />
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Panel>
  );
}

/* ============================================================
   CIRCUIT MAP (professional fallback)
   ============================================================ */

export function CircuitMap() {
  const st = useSessionState();
  const { selectedDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const board: any[] = snap?.leaderboard ?? [];

  return (
    <Panel title={`TRACK MAP ${snap?.circuit_short_name ? `// ${snap.circuit_short_name.toUpperCase()}` : ""}`}
           className="circuit-panel">
      {board.length === 0 ? (
        <p className="dim text-sm uppercase">WAITING FOR POSITION DATA</p>
      ) : (
        <>
          <div className="pos-strip">
            {board.map((row: any) => (
              <span key={row.driver_number}
                className={`pos-dot ${row.position === 1 ? "leader" : ""} ${selectedDriver === row.driver_number ? "selected" : ""}`}
                title={`P${row.position} #${row.driver_number}`}>
                P{row.position}&nbsp;
                <strong>{row.driver_number}</strong>
                {row.in_pit && <span style={{ color: "var(--warning)", marginLeft: 3, fontSize: "8px" }}>PIT</span>}
              </span>
            ))}
          </div>
          <p className="dim text-xs uppercase" style={{ marginTop: "var(--sp-2)" }}>
            CIRCUIT GEOMETRY UNAVAILABLE — POSITION ORDER SHOWN
          </p>
        </>
      )}
    </Panel>
  );
}

/* ============================================================
   RACE CONTROL FEED — enhanced with all event types
   ============================================================ */

export function RCFeed() {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const events: any[] = snap?.recent_events ?? [];
  const [filter, setFilter] = useState("ALL");

  const filters = ["ALL", "RC", "TIMING", "BATTLE", "TYRE", "STRATEGY"];

  const filtered = useMemo(() => {
    if (filter === "ALL") return events;
    return events.filter((e: any) => {
      const type = e.event_type ?? e.type ?? "";
      if (filter === "RC") return ["RED_FLAG", "SAFETY_CAR", "VSC", "SESSION_STATE_CHANGE"].includes(type);
      if (filter === "TIMING") return ["FASTEST_LAP_CHANGE", "PACE_CHANGE", "PACE_DROP"].includes(type);
      if (filter === "BATTLE") return ["OVERTAKE", "BATTLE_FORMED", "BATTLE_RESOLVED"].includes(type);
      if (filter === "TYRE") return ["PIT_STOP", "TYRE_DEGRADATION"].includes(type);
      if (filter === "STRATEGY") return ["STRATEGY_DEVIATION"].includes(type);
      return true;
    });
  }, [events, filter]);

  return (
    <Panel title="RACE CONTROL & EVENTS" className="rc-panel event-rail">
      <div className="event-filters">
        {filters.map((f) => (
          <button key={f} className={`ev-filter-btn ${filter === f ? "active" : ""}`}
                  onClick={() => setFilter(f)}>
            {f}
          </button>
        ))}
      </div>
      <ul className="event-list" style={{ maxHeight: 200, overflowY: "auto" }}>
        {filtered.length === 0 ? (
          <li className="event-item dim">NO EVENTS</li>
        ) : (
          [...filtered].reverse().slice(0, 30).map((ev: any, i: number) => (
            <li key={i} className="event-item">
              <span className="event-icon">{eventIcon(ev.event_type ?? ev.type ?? "")}</span>
              <span className="event-time">{fmtTime(ev.ts ?? ev.timestamp)}</span>
              <span className="event-text">{ev.description ?? ev.message ?? ev.event_type ?? ""}</span>
            </li>
          ))
        )}
      </ul>
    </Panel>
  );
}

/* ============================================================
   SECTOR INTEL (summary)
   ============================================================ */

export function SectorIntel() {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const leaders = snap?.sector_leaders ?? {};

  return (
    <Panel title="SECTOR INTEL & PACE">
      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        {[1, 2, 3].map((s) => {
          const sl = leaders[`S${s}`] ?? leaders[s];
          return (
            <div key={s} className="metric" style={{
              padding: "var(--sp-2)", textAlign: "center",
              background: "var(--surface-trace)", borderRadius: "var(--radius)",
              border: "1px solid var(--border)",
            }}>
              <span className="metric-label" style={{ color: "var(--sector-purple)" }}>S{s}</span>
              <span className="metric-value mono">
                {sl?.time_s != null ? fmtSec(sl.time_s) : UNAVAILABLE}
              </span>
              {sl?.driver != null && (
                <span className="dim text-xs mono">#{sl.driver}</span>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
