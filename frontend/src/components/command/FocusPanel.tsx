/**
 * Focus (Phase 11): the selected driver at the cursor frame - every value from
 * the frame row, the stint records and the pit records - with a one-step entry
 * into the Evidence Workbench. Without a selection it shows the session
 * summary: fastest lap, sector bests, provenance and limitations.
 */

import { useMemo, useState } from "react";
import { fetchLapCatalog } from "../../command/api";
import {
  compoundInfo, driverCode, fmtGap, fmtInterval, fmtInt, fmtLapTime, fmtSigned,
} from "../../command/format";
import type { Moment } from "../../command/moment";
import { dataOf, useResource } from "../../command/useResource";
import { Badge, DriverChip, EmptyState, Icon, Panel, Readout, TyreChip } from "./ui";

const SECTOR_WORD: Record<string, string> = { PURPLE: "session best", GREEN: "personal best", YELLOW: "slower than PB" };

function CompareEntry({ moment, driver }: { moment: Moment; driver: number }) {
  const sid = moment.timeline.session?.session_id ?? null;
  const catalog = useResource(sid, fetchLapCatalog);
  const cat = dataOf(catalog);
  const row = moment.row.get(driver);
  // default comparison: the car directly ahead at this moment (behind for the leader), until picked
  const neighbour = moment.rows.find((r) => row?.position != null && r.position === row.position - 1)
    ?? moment.rows.find((r) => row?.position != null && r.position === row.position + 1);
  const [picked, setPicked] = useState<number | null>(null);
  const other = picked ?? neighbour?.driver_number ?? null;
  const usable = (n: number | null) => (cat?.drivers.find((d) => d.driver_number === n)?.laps ?? [])
    .filter((l) => l.duration_s != null && l.has_car_telemetry && !l.deleted);
  const lapsA = usable(driver);
  const lapsB = usable(other);
  const [lapA, setLapA] = useState<number | null>(null);
  const [lapB, setLapB] = useState<number | null>(null);
  const a = lapA ?? lapsA.find((l) => l.lap_number === row?.lap_number)?.lap_number ?? lapsA[lapsA.length - 1]?.lap_number ?? null;
  const b = lapB ?? lapsB.find((l) => l.lap_number === a)?.lap_number ?? lapsB[lapsB.length - 1]?.lap_number ?? null;
  const href = sid && other != null && a != null && b != null
    ? `/evidence?${new URLSearchParams({ session: sid, driver_a: String(driver), lap_a: String(a), driver_b: String(other), lap_b: String(b) })}`
    : null;

  if (catalog.status === "error") {
    return <p className="cc-small cc-muted">Lap comparison unavailable: {catalog.error.message}</p>;
  }
  return (
    <div className="cc-compare">
      <p className="cc-label">Compare laps · Evidence Workbench</p>
      <div className="cc-compare-grid">
        <label className="cc-field"><span className="cc-label">Lap</span>
          <select value={a ?? ""} onChange={(e) => setLapA(Number(e.target.value))} disabled={!lapsA.length}>
            {lapsA.map((l) => <option key={l.lap_number} value={l.lap_number}>L{l.lap_number} · {fmtLapTime(l.duration_s)}</option>)}
          </select>
        </label>
        <label className="cc-field"><span className="cc-label">vs driver</span>
          <select value={other ?? ""} onChange={(e) => { setPicked(Number(e.target.value) || null); setLapB(null); }}>
            <option value="">Choose…</option>
            {moment.rows.filter((r) => r.driver_number !== driver).map((r) => (
              <option key={r.driver_number} value={r.driver_number}>P{r.position ?? "—"} {driverCode(moment.driver.get(r.driver_number), r.driver_number)}</option>
            ))}
          </select>
        </label>
        <label className="cc-field"><span className="cc-label">Lap</span>
          <select value={b ?? ""} onChange={(e) => setLapB(Number(e.target.value))} disabled={!lapsB.length}>
            {lapsB.map((l) => <option key={l.lap_number} value={l.lap_number}>L{l.lap_number} · {fmtLapTime(l.duration_s)}</option>)}
          </select>
        </label>
      </div>
      {catalog.status === "loading" && <p className="cc-small cc-muted" role="status">Loading stored laps…</p>}
      {cat && !lapsA.length && <p className="cc-small cc-muted">No lap of this driver has a time and stored telemetry.</p>}
      {href ? (
        <a className="cc-btn cc-btn-primary" href={href}><Icon name="compare" size={13} /> Open lap comparison</a>
      ) : (
        <span className="cc-btn is-disabled" aria-disabled="true"><Icon name="compare" size={13} /> Open lap comparison</span>
      )}
      <p className="cc-small cc-muted">Only laps with a time and stored telemetry are offered. The lap length and its source are entered in the workbench; no circuit geometry is stored.</p>
    </div>
  );
}

function DriverFocus({ moment, driver, onClose, onSeek }: {
  moment: Moment; driver: number; onClose: () => void; onSeek: (index: number) => void;
}) {
  const row = moment.row.get(driver);
  const id = moment.driver.get(driver);
  const stints = moment.stints.get(driver) ?? [];
  const pits = useMemo(() => moment.pits.filter((p) => p.driver_number === driver), [moment.pits, driver]);
  const battles = moment.battles.filter((b) => b.ahead === driver || b.behind === driver);
  if (!row) {
    return <EmptyState title="Not in this frame" why={`Car ${driver} has no timing row at this moment.`} />;
  }
  const fastest = moment.frame.fastest_lap?.driver === driver;
  return (
    <div className="cc-focus">
      <div className="cc-focus-head">
        <DriverChip driver={id} num={driver} size="lg" />
        <div className="cc-focus-name">
          <p>{id?.full_name ?? `Car ${driver}`}</p>
          <p className="cc-muted cc-small">{id?.team_name ?? "Team not recorded"}</p>
        </div>
        <button type="button" className="cc-btn cc-btn-icon" onClick={onClose} aria-label="Close driver focus"><Icon name="x" /></button>
      </div>
      <div className="cc-focus-hero">
        <div><span className="cc-label">Position</span><span className="cc-hero-num">P{row.position ?? "—"}</span></div>
        <div><span className="cc-label">Gap</span><span className="cc-hero-sub">{fmtGap(row)}</span></div>
        <div><span className="cc-label">Interval</span><span className="cc-hero-sub">{fmtInterval(row)}</span></div>
        <div><span className="cc-label">Laps</span><span className="cc-hero-sub">{fmtInt(row.lap_number)}</span></div>
      </div>
      <dl className="cc-readouts cc-readouts-3">
        <Readout label="Last lap" value={fmtLapTime(row.last_lap_s)} />
        <Readout label="Best lap" value={fmtLapTime(row.personal_best_s)} sub={fastest ? "session fastest" : undefined} />
        <Readout label="Stops" value={String(row.pit_stops)} sub={row.in_pit ? "in pit now" : undefined} />
        <Readout label="Tyre" value={<TyreChip compound={row.compound} />}
                 sub={row.tyre_laps_on_set != null ? `${row.tyre_laps_on_set} laps on set (${row.tyre_age_at_start ?? "?"} at fit)` : "age not recorded"} />
        <Readout label="Rolling 5" value={fmtLapTime(row.rolling5_s)} sub={<Badge tone="derived">C DERIVED</Badge>} />
        <Readout label="Pace trend" value={`${fmtSigned(row.pace_trend_s_per_lap)} s/lap`} sub={<Badge tone="derived">C DERIVED</Badge>} />
      </dl>
      <div className="cc-focus-block">
        <p className="cc-label">Last sectors</p>
        <div className="cc-focus-sectors">
          {["S1", "S2", "S3"].map((s) => {
            const c = row.sectors_last[s];
            return (
              <div key={s} className={`cc-focus-sector cc-sector-${c?.status?.toLowerCase() ?? "none"}`}>
                <span className="cc-label">{s}</span>
                <span className="cc-mono">{c ? c.time_s.toFixed(3) : "—"}</span>
                <span className="cc-small">{c?.status ? SECTOR_WORD[c.status] : "not recorded"}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="cc-focus-block">
        <p className="cc-label">Stints so far</p>
        <ol className="cc-focus-stints">
          {stints.length === 0 && <li className="cc-muted cc-small">No stint record yet.</li>}
          {stints.map((s) => (
            <li key={s.stint_number}>
              <TyreChip compound={s.compound} compact />
              <span className="cc-mono">L{s.lap_start ?? "?"}–{s.current ? `${s.drawEnd ?? "?"} (now)` : s.lap_end ?? "?"}</span>
              <span className="cc-muted cc-small">{compoundInfo(s.compound).label.toLowerCase()}{s.tyre_age_at_start ? `, ${s.tyre_age_at_start} laps old at fit` : ", new at fit"}</span>
            </li>
          ))}
        </ol>
      </div>
      {pits.length > 0 && (
        <div className="cc-focus-block">
          <p className="cc-label">Pit stops</p>
          <ol className="cc-focus-pits">
            {pits.map((p) => (
              <li key={p.ts}>
                <button type="button" className="cc-link" onClick={() => onSeek(p.frame_index)}>L{p.lap_number ?? "?"}</button>
                <TyreChip compound={p.compound_before} compact /><span aria-hidden="true">→</span>
                {p.compound_after ? <TyreChip compound={p.compound_after} compact /> : <span className="cc-muted cc-small">no change</span>}
                <span className="cc-mono cc-muted">{p.lane_duration_s != null ? `${p.lane_duration_s.toFixed(1)} s lane` : ""}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {battles.length > 0 && (
        <p className="cc-small">In battle with {battles.map((b) => {
          const o = b.ahead === driver ? b.behind : b.ahead;
          return `${driverCode(moment.driver.get(o), o)} (${b.last_gap_s != null ? `${b.last_gap_s.toFixed(3)} s` : "—"})`;
        }).join(", ")}</p>
      )}
      <CompareEntry key={driver} moment={moment} driver={driver} />
    </div>
  );
}

function SessionSummary({ moment }: { moment: Moment }) {
  const t = moment.timeline;
  const fl = moment.frame.fastest_lap;
  const [showLimits, setShowLimits] = useState(false);
  return (
    <div className="cc-focus">
      <p className="cc-small cc-muted">Select a driver in the timing tower or the chart to focus on them.</p>
      <dl className="cc-readouts cc-readouts-2">
        <Readout label="Fastest lap" wide
          value={fl?.driver != null ? <>{driverCode(moment.driver.get(fl.driver), fl.driver)} · {fmtLapTime(fl.duration_s)}</> : "—"}
          sub={fl?.at_lap != null ? `set on lap ${fl.at_lap}` : undefined} />
        {["S1", "S2", "S3"].map((s) => {
          const l = moment.frame.sector_leaders[s];
          return <Readout key={s} label={`${s} best`} value={l ? `${l.time_s.toFixed(3)}` : "—"}
                          sub={l ? driverCode(moment.driver.get(l.driver), l.driver) : undefined} />;
        })}
      </dl>
      <div className="cc-focus-block">
        <p className="cc-label">Provenance</p>
        <p className="cc-small">
          {t.source.kind === "RECORDING" ? `Recording ${t.source.recording ?? ""}` : "Live hub capture"} · provider {t.source.provider ?? "—"}
          · {t.source.envelopes_folded.toLocaleString()} events folded
        </p>
        <p className="cc-small cc-muted cc-mono cc-break">{t.builder_version} · {t.calc_version} · {t.source.input_digest.slice(0, 23)}…</p>
      </div>
      <div className="cc-focus-block">
        <button type="button" className="cc-disclose" aria-expanded={showLimits} onClick={() => setShowLimits((v) => !v)}>
          <Icon name="info" size={13} /> Limitations ({t.limitations.length})
        </button>
        {showLimits && (
          <ul className="cc-limits">
            {t.limitations.map((l) => <li key={l.code}><code>{l.code}</code> {l.message}</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}

export function FocusPanel({ moment, driver, onClose, onSeek }: {
  moment: Moment; driver: number | null; onClose: () => void; onSeek: (index: number) => void;
}) {
  return (
    <Panel id="cc-focus" title={driver != null ? "Driver focus" : "Session"} className="cc-focus-panel"
      meta={driver != null ? <span>at {moment.isStart ? "the start" : moment.isFinal ? "the end" : `lap ${moment.lap}`}</span> : undefined}>
      {driver != null
        ? <DriverFocus moment={moment} driver={driver} onClose={onClose} onSeek={onSeek} />
        : <SessionSummary moment={moment} />}
    </Panel>
  );
}
