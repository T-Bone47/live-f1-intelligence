/** Broadcast-quality timing tower with position-change indicators,
 *  tyre chips, monospaced alignment, and driver selection. */

import { memo, useEffect, useRef } from "react";
import { useSessionState } from "../../state/store";
import { Panel, TyreChip } from "../shared";

interface Row {
  position: number | null;
  driver_number: number;
  lap_number: number | null;
  last_lap_s: number | null;
  personal_best_s: number | null;
  gap_to_leader_raw: string | null;
  gap_to_leader_s: number | null;
  interval_s: number | null;
  compound: string | null;
  tyre_age: number | null;
  rolling5_s: number | null;
  pace_trend_s_per_lap: number | null;
  in_pit: boolean;
  retired: boolean;
}

function fmtLap(v: number | null): string {
  if (v == null) return "\u2014";
  const m = Math.floor(v / 60);
  const s = (v % 60).toFixed(3);
  return m > 0 ? `${m}:${s.padStart(6, "0")}` : s;
}

function fmtGap(row: Row): string {
  if (row.position === 1) return "LEADER";
  if (row.gap_to_leader_raw) return row.gap_to_leader_raw;
  if (row.gap_to_leader_s != null) return `+${row.gap_to_leader_s.toFixed(3)}`;
  return "\u2014";
}

function fmtInterval(row: Row): string {
  if (row.interval_s == null) return "\u2014";
  return `+${row.interval_s.toFixed(3)}`;
}

const TimingRow = memo(function TimingRow({ row, prevPos, selected, onSelect }: {
  row: Row; prevPos: number | undefined; selected: boolean;
  onSelect: (n: number) => void;
}) {
  const posDelta = prevPos != null && row.position != null
    ? prevPos - row.position : 0;
  const isLeader = row.position === 1;

  return (
    <tr className={`tt-row ${selected ? "selected" : ""} ${row.retired ? "retired" : ""}`}
        onClick={() => onSelect(row.driver_number)}>
      <td className="tt-pos">{String(row.position ?? "?").padStart(2, "0")}</td>
      <td className="tt-delta-pos" aria-label={`Position change: ${posDelta >= 0 ? "up" : "down"} ${Math.abs(posDelta)}`}>
        {posDelta > 0 ? <span className="up">\u25B2</span> :
         posDelta < 0 ? <span className="dn">\u25BC</span> :
         <span className="same">{"\u2014"}</span>}
      </td>
      <td className="tt-driver">{row.driver_number}</td>
      <td className="tt-gap mono">{isLeader ? "LDR" : fmtGap(row)}</td>
      <td className="tt-int mono">{isLeader ? "\u2014" : fmtInterval(row)}</td>
      <td className="tt-lap">{row.lap_number ?? "\u2014"}</td>
      <td className="tt-last mono">{fmtLap(row.last_lap_s)}</td>
      <td className="tt-best mono pb">{fmtLap(row.personal_best_s)}</td>
      <td className="tt-tyre"><TyreChip compound={row.compound} age={row.tyre_age} /></td>
      <td className="tt-pace mono dim">
        {row.rolling5_s != null ? row.rolling5_s.toFixed(1) : "\u2014"}
      </td>
    </tr>
  );
});


export function TimingTower() {
  const st = useSessionState();
  const rows: any[] = st.snapshot?.leaderboard ?? [];
  const prevPositions = useRef<Map<number, number>>(new Map());

  useEffect(() => {
    const nextMap = new Map<number, number>();
    for (const r of rows) {
      if (r.driver_number != null && r.position != null)
        nextMap.set(r.driver_number, r.position);
    }
    prevPositions.current = nextMap;
  }, [rows]);

  return (
    <div className="timing-tower-wrap">
      <table className="tt-table" role="table" aria-label="Live timing tower">
        <thead>
          <tr>
            {["POS", "\u0394", "DRV", "GAP", "INT", "LAP", "LAST", "BEST", "TYRE", "PACE"].map(h => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={10} className="tt-empty">WAITING FOR TIMING DATA</td></tr>
          ) : (
            rows.map((r: any) => (
              <TimingRow key={r.driver_number} row={r}
                         prevPos={prevPositions.current.get(r.driver_number)}
                         selected={false} onSelect={() => {}} />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
