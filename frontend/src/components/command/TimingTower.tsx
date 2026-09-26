/**
 * Timing tower (Phase 11): the backend's leaderboard at the cursor frame.
 * Every value is the frame row's; the only logic is ordering by the backend
 * position, equality checks for markers (PB / fastest lap) and formatting.
 *
 * Motion: when the cursor moves, rows glide to their new position (FLIP,
 * transform only, skipped under reduced motion); a changed gap briefly tints.
 */

import { memo, useCallback, useLayoutEffect, useRef, type KeyboardEvent } from "react";
import { fmtGap, fmtInterval, fmtLapTime, fmtInt } from "../../command/format";
import type { Moment } from "../../command/moment";
import type { Density } from "../../command/state";
import type { DriverIdentity, TimingRow } from "../../command/types";
import { Badge, DriverChip, Icon, Panel, Tick, TyreChip } from "./ui";

const SECTOR_TEXT: Record<string, string> = {
  PURPLE: "purple (session best at the time)", GREEN: "green (personal best)", YELLOW: "yellow (slower than personal best)",
};

function PositionChange({ change }: { change: number | null }) {
  if (change == null) return <span className="cc-pc cc-pc-none" aria-hidden="true" />;
  if (change === 0) return <span className="cc-pc cc-pc-same"><span className="cc-sr">no change</span>–</span>;
  const up = change > 0;
  return (
    <span className={`cc-pc ${up ? "cc-pc-up" : "cc-pc-down"}`}>
      <Icon name={up ? "arrowUp" : "arrowDown"} size={10} />
      {Math.abs(change)}
      <span className="cc-sr">{up ? " places gained" : " places lost"} since the previous lap</span>
    </span>
  );
}

function Sectors({ row }: { row: TimingRow }) {
  return (
    <span className="cc-sectors">
      {["S1", "S2", "S3"].map((s) => {
        const c = row.sectors_last[s];
        const cls = c?.status ? `cc-sector-${c.status.toLowerCase()}` : "cc-sector-none";
        const text = c ? `${s} ${c.time_s.toFixed(3)} s, ${SECTOR_TEXT[c.status ?? ""] ?? "no status"}` : `${s} not recorded`;
        return <span key={s} className={`cc-sector ${cls}`} title={text}><span className="cc-sr">{text}</span></span>;
      })}
    </span>
  );
}

const Row = memo(function Row({ row, driver, selected, inBattle, fastest, density, focusable, onSelect, onKey }: {
  row: TimingRow; driver: DriverIdentity | undefined; selected: boolean; inBattle: boolean;
  fastest: boolean; density: Density; focusable: boolean;
  onSelect: (n: number) => void; onKey: (e: KeyboardEvent<HTMLTableRowElement>, n: number) => void;
}) {
  const gap = fmtGap(row);
  const pb = row.last_lap_s != null && row.last_lap_s === row.personal_best_s;
  return (
    <tr data-driver={row.driver_number} tabIndex={focusable ? 0 : -1} aria-selected={selected}
        className={`cc-tt-row${selected ? " is-selected" : ""}${inBattle ? " is-battle" : ""}${row.in_pit ? " is-pit" : ""}`}
        onClick={() => onSelect(row.driver_number)} onKeyDown={(e) => onKey(e, row.driver_number)}>
      <td className="cc-tt-pos">{row.position ?? "—"}</td>
      <td className="cc-tt-pc"><PositionChange change={row.position_change} /></td>
      <td className="cc-tt-driver"><DriverChip driver={driver} num={row.driver_number} showNumber={density === "standard"} /></td>
      <td className="cc-tt-num cc-tt-gap"><Tick value={gap} /></td>
      <td className="cc-tt-num cc-tt-int"><Tick value={fmtInterval(row)} /></td>
      {density === "standard" && <>
        <td className="cc-tt-num cc-tt-lap">{fmtInt(row.lap_number)}</td>
        <td className="cc-tt-num cc-tt-last">
          {fmtLapTime(row.last_lap_s)}{pb && <span className="cc-mark cc-mark-pb" title="Last lap is this driver's personal best">PB</span>}
        </td>
        <td className="cc-tt-num cc-tt-best">
          {fmtLapTime(row.personal_best_s)}{fastest && <span className="cc-mark cc-mark-fl" title="Session fastest lap">FL</span>}
        </td>
        <td className="cc-tt-sectors"><Sectors row={row} /></td>
      </>}
      <td className="cc-tt-tyre"><TyreChip compound={row.compound} laps={row.tyre_laps_on_set} compact /></td>
      {density === "standard" && <td className="cc-tt-num cc-tt-stops">{row.pit_stops}</td>}
      <td className="cc-tt-state">{row.in_pit ? <Badge tone="warning" title="From the pit-stop record until the out-lap is completed">PIT</Badge> : null}</td>
    </tr>
  );
});

export function TimingTower({ moment, selected, battlePair, density, onSelect, onDensity }: {
  moment: Moment; selected: number | null; battlePair: [number, number] | null; density: Density;
  onSelect: (n: number | null) => void; onDensity: (d: Density) => void;
}) {
  const body = useRef<HTMLTableSectionElement>(null);
  const tops = useRef(new Map<number, number>());
  const fastestDriver = moment.frame.fastest_lap?.driver ?? null;

  // FLIP: animate rows from their previous offset to the new one when the order changes.
  useLayoutEffect(() => {
    const el = body.current;
    if (!el) return;
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const next = new Map<number, number>();
    el.querySelectorAll<HTMLTableRowElement>("tr[data-driver]").forEach((tr) => {
      const n = Number(tr.dataset.driver);
      next.set(n, tr.offsetTop);
      const prev = tops.current.get(n);
      if (!reduce && prev != null && prev !== tr.offsetTop) {
        tr.animate?.([{ transform: `translateY(${prev - tr.offsetTop}px)` }, { transform: "translateY(0)" }],
          { duration: 320, easing: "cubic-bezier(0.16, 1, 0.3, 1)" });
      }
    });
    tops.current = next;
  }, [moment.index]);

  const onKey = useCallback((e: KeyboardEvent<HTMLTableRowElement>, n: number) => {
    const rows = Array.from(body.current?.querySelectorAll<HTMLTableRowElement>("tr[data-driver]") ?? []);
    const i = rows.findIndex((r) => Number(r.dataset.driver) === n);
    const go = (j: number) => { e.preventDefault(); rows[Math.max(0, Math.min(rows.length - 1, j))]?.focus(); };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(rows.length - 1);
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(n); }
    else if (e.key === "Escape") onSelect(null);
  }, [onSelect]);

  const toggle = useCallback((n: number) => onSelect(selected === n ? null : n), [selected, onSelect]);
  const focusable = selected ?? moment.rows[0]?.driver_number;
  return (
    <Panel id="cc-timing" title="Timing" className="cc-timing"
      meta={<span>{moment.rows.length} cars · order = backend position</span>}
      actions={
        <div className="cc-seg" role="group" aria-label="Row density">
          {(["standard", "compact"] as const).map((d) => (
            <button key={d} type="button" className="cc-seg-btn" aria-pressed={density === d} onClick={() => onDensity(d)}>
              {d === "standard" ? "Full" : "Compact"}
            </button>
          ))}
        </div>
      }>
      <div className="cc-tt-wrap">
        <table className={`cc-tt cc-tt-${density}`} aria-label={`Timing at ${moment.isFinal ? "the end of the recording" : moment.isStart ? "the start" : `the end of lap ${moment.lap}`}`}>
          <thead>
            <tr>
              <th scope="col" className="cc-tt-pos">P</th>
              <th scope="col" className="cc-tt-pc"><span className="cc-sr">Position change</span></th>
              <th scope="col" className="cc-tt-driver">Driver</th>
              <th scope="col" className="cc-tt-num">Gap</th>
              <th scope="col" className="cc-tt-num">Int</th>
              {density === "standard" && <>
                <th scope="col" className="cc-tt-num cc-tt-lap">Lap</th>
                <th scope="col" className="cc-tt-num cc-tt-last">Last</th>
                <th scope="col" className="cc-tt-num cc-tt-best">Best</th>
                <th scope="col" className="cc-tt-sectors">Sectors</th>
              </>}
              <th scope="col" className="cc-tt-tyre">Tyre</th>
              {density === "standard" && <th scope="col" className="cc-tt-num cc-tt-stops" title="Pit stops recorded so far">Stops</th>}
              <th scope="col" className="cc-tt-state"><span className="cc-sr">State</span></th>
            </tr>
          </thead>
          <tbody ref={body}>
            {moment.rows.map((r) => (
              <Row key={r.driver_number} row={r} driver={moment.driver.get(r.driver_number)}
                   selected={selected === r.driver_number}
                   inBattle={!!battlePair && battlePair.includes(r.driver_number)}
                   fastest={fastestDriver === r.driver_number} density={density}
                   focusable={focusable === r.driver_number}
                   onSelect={toggle} onKey={onKey} />
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
