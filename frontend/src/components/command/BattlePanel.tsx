/**
 * Battles (Phase 11): the backend BattleDetector's pairs at the cursor frame -
 * only neighbours, state verbatim, gap = the detector's last measured
 * interval. Nothing is detected or ranked in the browser beyond ordering by
 * the ahead car's backend position.
 *
 * Selected battle: the behind car's measured interval at each lap frame while
 * the two cars were neighbours (points only; not a fitted curve).
 */

import { useMemo } from "react";
import { battleState, driverCode, fmtLapTime, fmtSigned, teamColour } from "../../command/format";
import { battleKey, pairIntervalHistory, type Moment } from "../../command/moment";
import type { Battle } from "../../command/types";
import { Badge, DriverChip, EmptyState, Panel, Tick, TyreChip } from "./ui";
import { useWidth } from "./useWidth";

function BattleCard({ b, moment, selected, onSelect }: {
  b: Battle; moment: Moment; selected: boolean; onSelect: (key: string | null) => void;
}) {
  const a = moment.row.get(b.ahead);
  const z = moment.row.get(b.behind);
  const st = battleState(b.state);
  const key = battleKey(b);
  return (
    <button type="button" className={`cc-battle${selected ? " is-selected" : ""}`} aria-pressed={selected}
            onClick={() => onSelect(selected ? null : key)}
            aria-label={`Battle P${a?.position ?? "?"} ${driverCode(moment.driver.get(b.ahead), b.ahead)} ahead of P${z?.position ?? "?"} ${driverCode(moment.driver.get(b.behind), b.behind)}, gap ${b.last_gap_s ?? "not measured"} seconds, ${st.label}`}>
      <span className="cc-battle-side">
        <span className="cc-battle-pos">P{a?.position ?? "—"}</span>
        <DriverChip driver={moment.driver.get(b.ahead)} num={b.ahead} showNumber={false} />
        <TyreChip compound={a?.compound ?? null} laps={a?.tyre_laps_on_set} compact />
      </span>
      <span className="cc-battle-gap">
        <Tick value={b.last_gap_s != null ? b.last_gap_s.toFixed(3) : "—"} />
        <span className="cc-battle-unit">s</span>
      </span>
      <span className="cc-battle-side">
        <span className="cc-battle-pos">P{z?.position ?? "—"}</span>
        <DriverChip driver={moment.driver.get(b.behind)} num={b.behind} showNumber={false} />
        <TyreChip compound={z?.compound ?? null} laps={z?.tyre_laps_on_set} compact />
      </span>
      <span className="cc-battle-state" title={st.detail}><Badge tone="neutral">{st.label}</Badge></span>
    </button>
  );
}

function GapHistory({ moment, battle }: { moment: Moment; battle: Battle }) {
  const [wrap, width] = useWidth<HTMLDivElement>(420);
  const t = moment.timeline;
  const pts = useMemo(() => pairIntervalHistory(t, battle.ahead, battle.behind, moment.index)
    .filter((p) => p.interval != null && p.lap != null), [t, battle.ahead, battle.behind, moment.index]);
  const total = Math.max(t.laps_completed_max ?? 1, 1);
  const H = 120;
  const M = { l: 36, r: 10, t: 10, b: 20 };
  const plotW = Math.max(width - M.l - M.r, 60);
  const ymax = Math.max(1, ...pts.map((p) => p.interval as number));
  const x = (lap: number) => M.l + (lap / total) * plotW;
  const y = (v: number) => M.t + (v / ymax) * (H - M.t - M.b);   // 0 s at top: closer = higher
  const behind = moment.driver.get(battle.behind);
  const colour = teamColour(behind) ?? "var(--text-secondary)";
  const a = moment.row.get(battle.ahead);
  const z = moment.row.get(battle.behind);
  return (
    <div className="cc-battle-detail">
      <div className="cc-battle-detail-head">
        <p className="cc-label">Interval · {driverCode(behind, battle.behind)} to {driverCode(moment.driver.get(battle.ahead), battle.ahead)}</p>
        <p className="cc-muted cc-small">Measured interval at each lap end while they were neighbours · 0 s at the top</p>
      </div>
      <div ref={wrap} className="cc-chart-wrap">
        <svg width={width} height={H} role="img" className="cc-gap-chart"
             aria-label={`Interval history, ${pts.length} measured lap ends`}>
          <rect x={M.l} y={M.t} width={plotW} height={H - M.t - M.b} className="cc-plot-bg" />
          {[0, ymax / 2, ymax].map((v) => (
            <g key={v}>
              <line x1={M.l} x2={M.l + plotW} y1={y(v)} y2={y(v)} className="cc-gridline" />
              <text x={M.l - 5} y={y(v) + 3.5} textAnchor="end" className="cc-axis">{v.toFixed(1)}s</text>
            </g>
          ))}
          {pts.length > 1 && (
            <polyline fill="none" stroke={colour} strokeWidth={1.25} strokeOpacity={0.45}
                      points={pts.map((p) => `${x(p.lap!)},${y(p.interval!)}`).join(" ")} />
          )}
          {pts.map((p) => <circle key={p.index} cx={x(p.lap!)} cy={y(p.interval!)} r={2.25} fill={colour} />)}
          <text x={M.l} y={H - 6} className="cc-axis">START</text>
          <text x={M.l + plotW} y={H - 6} textAnchor="end" className="cc-axis">L{total}</text>
        </svg>
      </div>
      <dl className="cc-readouts cc-readouts-3">
        <div className="cc-readout"><dt className="cc-label">Min gap</dt><dd className="cc-readout-value">{battle.min_gap_s != null ? `${battle.min_gap_s.toFixed(3)} s` : "—"}</dd></div>
        <div className="cc-readout"><dt className="cc-label">Last lap · ahead</dt><dd className="cc-readout-value">{fmtLapTime(a?.last_lap_s)}</dd></div>
        <div className="cc-readout"><dt className="cc-label">Last lap · behind</dt><dd className="cc-readout-value">{fmtLapTime(z?.last_lap_s)}</dd></div>
        <div className="cc-readout"><dt className="cc-label">Rolling 5 · ahead</dt><dd className="cc-readout-value">{fmtLapTime(a?.rolling5_s)}</dd><dd className="cc-readout-sub"><Badge tone="derived">C DERIVED</Badge></dd></div>
        <div className="cc-readout"><dt className="cc-label">Rolling 5 · behind</dt><dd className="cc-readout-value">{fmtLapTime(z?.rolling5_s)}</dd><dd className="cc-readout-sub"><Badge tone="derived">C DERIVED</Badge></dd></div>
        <div className="cc-readout"><dt className="cc-label">DRS</dt><dd className="cc-readout-value cc-muted">Unavailable</dd><dd className="cc-readout-sub">not in this data</dd></div>
      </dl>
      <p className="cc-small cc-muted">Pace trend · ahead {fmtSigned(a?.pace_trend_s_per_lap)} s/lap · behind {fmtSigned(z?.pace_trend_s_per_lap)} s/lap (engine slope, derived)</p>
    </div>
  );
}

export function BattlePanel({ moment, selected, onSelect }: {
  moment: Moment; selected: string | null; onSelect: (key: string | null) => void;
}) {
  const battles = useMemo(() => [...moment.battles].sort((p, q) =>
    (moment.row.get(p.ahead)?.position ?? 99) - (moment.row.get(q.ahead)?.position ?? 99)), [moment]);
  const active = battles.find((b) => battleKey(b) === selected) ?? null;
  return (
    <Panel id="cc-battles" title="Battles" className="cc-battles"
      meta={<span>{battles.length} between neighbours · battle detector</span>}>
      {battles.length === 0 ? (
        <EmptyState title="No battles at this moment"
          why="The battle detector reports no pair of neighbouring cars within its thresholds at this lap." />
      ) : (
        <div className="cc-battle-list" role="list">
          {battles.map((b) => (
            <div role="listitem" key={battleKey(b)}>
              <BattleCard b={b} moment={moment} selected={battleKey(b) === selected} onSelect={onSelect} />
            </div>
          ))}
        </div>
      )}
      {active && <GapHistory moment={moment} battle={active} />}
      {!active && selected && (
        <p className="cc-small cc-muted cc-pad">The selected pair is no longer a battle at this lap.</p>
      )}
    </Panel>
  );
}
