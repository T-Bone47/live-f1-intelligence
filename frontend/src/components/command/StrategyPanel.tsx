/**
 * Tyres & strategy (Phase 11) - observational only. Stint bars are the
 * provider's stint records, shown as far as each driver has got at the
 * cursor (the current stint ends at the driver's completed laps). Pit stops
 * are the observed records up to the cursor, with the compounds either side
 * joined by the backend. No strategy, window or undercut is inferred here.
 */

import { useMemo, useState } from "react";
import { compoundInfo, driverCode, fmtInt } from "../../command/format";
import type { Moment, VisibleStint } from "../../command/moment";
import { Badge, DriverChip, EmptyState, Panel, TyreChip } from "./ui";
import { useWidth } from "./useWidth";

const LABEL_W = 70;

function stintTitle(s: VisibleStint): string {
  const c = compoundInfo(s.compound).label;
  const end = s.current ? `L${s.drawEnd ?? s.lap_start} (in progress)` : `L${s.lap_end ?? "?"}`;
  const age = s.tyre_age_at_start != null ? `, ${s.tyre_age_at_start} laps old when fitted` : "";
  return `Stint ${s.stint_number}: ${c}, L${s.lap_start ?? "?"}–${end}${age}`;
}

export function StrategyPanel({ moment, selected, onSelectDriver, onSeek }: {
  moment: Moment; selected: number | null;
  onSelectDriver: (n: number | null) => void; onSeek: (index: number) => void;
}) {
  const [wrap, width] = useWidth<HTMLDivElement>(700);
  const [view, setView] = useState<"stints" | "pits">("stints");
  const t = moment.timeline;
  const total = Math.max(t.laps_completed_max ?? 1, 1);
  const trackW = Math.max(width - LABEL_W - 12, 80);
  const x = (lap: number) => (Math.max(0, lap - 1) / total) * trackW;
  const w = (a: number, b: number) => Math.max(2, ((b - a + 1) / total) * trackW);
  const cursorLap = moment.isStart ? 0 : moment.lap ?? 0;
  const pits = useMemo(() => [...moment.pits].reverse(), [moment.pits]);
  const hasStints = moment.stints.size > 0;

  return (
    <Panel id="cc-strategy" title="Tyres & strategy" className="cc-strategy"
      meta={<span>observed stints and stops · no prediction</span>}
      actions={
        <div className="cc-seg" role="group" aria-label="Strategy view">
          <button type="button" className="cc-seg-btn" aria-pressed={view === "stints"} onClick={() => setView("stints")}>Stints</button>
          <button type="button" className="cc-seg-btn" aria-pressed={view === "pits"} onClick={() => setView("pits")}>
            Pit stops <span className="cc-count">{moment.pits.length}</span>
          </button>
        </div>
      }>
      {view === "stints" && (
        !hasStints ? (
          <EmptyState title="Tyre data unavailable" why="No stint records have been reported for this session at this lap." />
        ) : (
          <div ref={wrap} className="cc-stints">
            <div className="cc-stint-legend" aria-hidden="true">
              {["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"].map((c) => <TyreChip key={c} compound={c} />)}
            </div>
            <ol className="cc-stint-rows" aria-label="Stints by driver, in running order">
              {moment.rows.map((r) => {
                const stints = moment.stints.get(r.driver_number) ?? [];
                const driverPits = moment.pits.filter((p) => p.driver_number === r.driver_number);
                const on = selected === r.driver_number;
                return (
                  <li key={r.driver_number} className={`cc-stint-row${on ? " is-selected" : ""}`}>
                    <button type="button" className="cc-stint-driver" aria-pressed={on}
                            onClick={() => onSelectDriver(on ? null : r.driver_number)}>
                      <span className="cc-stint-pos">{r.position ?? "—"}</span>
                      <DriverChip driver={moment.driver.get(r.driver_number)} num={r.driver_number} showNumber={false} size="sm" />
                    </button>
                    <div className="cc-stint-track" style={{ width: trackW }}>
                      {stints.map((s) => {
                        if (s.lap_start == null) return null;
                        const end = s.drawEnd ?? s.lap_start;
                        if (end < s.lap_start) return null;   // stint begun, no lap completed on it yet
                        const c = compoundInfo(s.compound);
                        const width_ = w(s.lap_start, end);
                        return (
                          <span key={s.stint_number} title={stintTitle(s)}
                                className={`cc-stint cc-stint-${c.token}${s.current ? " is-current" : ""}`}
                                style={{ left: x(s.lap_start), width: width_ }}>
                            {width_ > 26 && <span className="cc-stint-label">{c.short}{width_ > 60 ? ` ${end - s.lap_start + 1}` : ""}</span>}
                            <span className="cc-sr">{stintTitle(s)}</span>
                          </span>
                        );
                      })}
                      {driverPits.map((p) => p.lap_number != null && (
                        <span key={`${p.ts}`} className="cc-pit-mark" style={{ left: x(p.lap_number + 1) }}
                              title={`Pit stop, lap ${p.lap_number}`} aria-hidden="true" />
                      ))}
                      <span className="cc-stint-cursor" style={{ left: x(cursorLap + 1) }} aria-hidden="true" />
                    </div>
                  </li>
                );
              })}
            </ol>
            <p className="cc-small cc-muted cc-pad">
              Tick = pit stop. Number = laps on the stint so far. Undercut / overcut: {t.capabilities.undercut_overcut ? "provided" : "not provided by the backend"}.
            </p>
          </div>
        )
      )}
      {view === "pits" && (
        pits.length === 0 ? (
          <EmptyState title="No pit stops yet" why="No pit-stop record exists up to this lap." />
        ) : (
          <div className="cc-scroll-y">
            <table className="cc-table">
              <thead><tr><th scope="col">Lap</th><th scope="col">Driver</th><th scope="col">Tyres</th><th scope="col" className="cc-num">Pit lane</th><th scope="col"><span className="cc-sr">Go</span></th></tr></thead>
              <tbody>
                {pits.map((p) => (
                  <tr key={`${p.driver_number}-${p.ts}`} className={selected === p.driver_number ? "is-selected" : undefined}>
                    <td className="cc-num">L{fmtInt(p.lap_number)}</td>
                    <td><DriverChip driver={moment.driver.get(p.driver_number)} num={p.driver_number} showNumber={false} size="sm" /></td>
                    <td className="cc-tyre-change">
                      <TyreChip compound={p.compound_before} compact />
                      <span aria-hidden="true">→</span>
                      {p.compound_after ? <TyreChip compound={p.compound_after} compact />
                        : <Badge tone="neutral" title="No stint starts on the lap after this stop">no change recorded</Badge>}
                    </td>
                    <td className="cc-num">{p.lane_duration_s != null ? `${p.lane_duration_s.toFixed(1)} s` : "—"}</td>
                    <td>
                      <button type="button" className="cc-btn cc-btn-ghost"
                              onClick={() => { onSelectDriver(p.driver_number); onSeek(p.frame_index); }}
                              aria-label={`Go to ${driverCode(moment.driver.get(p.driver_number), p.driver_number)} pit stop on lap ${p.lap_number}`}>
                        Go
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="cc-small cc-muted cc-pad">Pit-lane time as recorded (entry to exit). Stationary time is not in this data.</p>
          </div>
        )
      )}
    </Panel>
  );
}
