/**
 * Track map (Phase 12B): the validated 12A evidence at the ONE cursor.
 * Everything drawn comes from track_reference_v1 and the spatial state the
 * backend returned for the cursor; the browser selects, orders, formats and
 * scales to pixels. No position, distance, sector or lap is computed here,
 * the camera never moves, and nothing old survives a session change.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { driverCode, fmtClockTenths, fmtAsOf, phaseLabel, phaseTone, teamColour } from "../../command/format";
import type { Moment } from "../../command/moment";
import { windowForRate } from "../../spatial/api";
import type { LineName } from "../../spatial/types";
import type { SpatialView } from "../../spatial/useSpatial";
import type { MapGhost } from "../../telemetry/useGhost";
import { ErrorState, Panel } from "../command/ui";
import { useWidth } from "../command/useWidth";
import { lineTagBox, mapFit, placeLabels } from "./geometry";
import { MapInfo } from "./MapInfo";
import { CircuitLayer, LineLayer } from "./MapLayers";
import { MapTable, NotOnMap, Tooltip } from "./MapParts";
import { Marker, type MarkerModel } from "./Markers";
import { REASON_TEXT, tagFor } from "./words";
import "./spatial.css";

function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => typeof matchMedia === "function" && matchMedia(query).matches);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const mq = matchMedia(query);
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

/** A hollow ring at the driver's own location sample, labelled with that sample's time. */
function Ghost({ ghost, at, width }: { ghost: MapGhost; at: [number, number]; width: number }) {
  const label = `#${ghost.driver} at ${fmtClockTenths(ghost.at)} (hovered)`;
  const flip = at[0] > width - 190;
  return (
    <g className="sm-ghost" role="img" aria-label={label} transform={`translate(${at[0].toFixed(1)} ${at[1].toFixed(1)})`}>
      <circle className="sm-ghost-ring" r={7.5} />
      <text className="sm-label sm-ghost-label" x={flip ? -11 : 11} y={-10} textAnchor={flip ? "end" : "start"}>{label}</text>
    </g>
  );
}

export const TrackMap = memo(function TrackMap({ view, moment, selected, battle, playing, rate, onSelect, onPositionSelect,
                                                ghost = null }: {
  view: SpatialView; moment: Moment; selected: number | null; battle: [number, number] | null;
  playing: boolean; rate: number; onSelect: (d: number | null) => void;
  onPositionSelect?: (driver: number, stateAt: string) => void;
  /** Phase 12C: a hovered telemetry sample's driver at its own location sample (never interpolated). */
  ghost?: MapGhost | null;
}) {
  const [frameRef, width] = useWidth<HTMLDivElement>(640);
  const [info, setInfo] = useState(false);
  const [line, setLine] = useState<LineName | null>(null);
  const [hotSector, setHotSector] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [focusN, setFocusN] = useState<number | null>(null);
  const reduced = useReducedMotion();
  const refs = useRef(new Map<number, SVGGElement>());
  const { track, shown } = view;
  const drawable = track?.status === "VALIDATED_MAP_SECTOR" && view.status !== "unavailable" ? track : null;
  const fit = useMemo(() => (drawable ? mapFit(drawable, width) : null), [drawable, width]);

  // cars the backend positions, in the current frame's order (P1 first)
  const order = useMemo(() => {
    const on = new Map((shown?.drivers ?? []).filter((d) => d.status !== "NO_COVERAGE" && d.x != null && d.y != null)
      .map((d) => [d.driver_number, d]));
    const ranked = moment.rows.map((r) => r.driver_number).filter((n) => on.has(n));
    return [...ranked, ...[...on.keys()].filter((n) => !ranked.includes(n)).sort((a, b) => a - b)].map((n) => on.get(n)!);
  }, [shown, moment.rows]);

  const models = useMemo((): MarkerModel[] => {
    if (!fit) return [];
    const p1 = moment.rows[0]?.driver_number;
    const pair = new Set(battle ?? []);
    const keyN = focusN != null && order.some((d) => d.driver_number === focusN) ? focusN
      : selected != null && order.some((d) => d.driver_number === selected) ? selected : order[0]?.driver_number;
    const base = order.map((d) => {
      const [x, y] = fit.toPx(d.x!, d.y!);
      const ident = moment.driver.get(d.driver_number);
      return { d, x, y, code: driverCode(ident, d.driver_number), colour: teamColour(ident) ?? "var(--state-unknown)",
               selected: d.driver_number === selected, battle: pair.has(d.driver_number),
               focusable: d.driver_number === keyN, label: null } as MarkerModel;
    });
    // labels: selected, battle pair, P1, hovered, then every tagged state
    const rank = (m: MarkerModel) => (m.selected ? 0 : m.battle ? 1 : m.d.driver_number === p1 ? 2
      : m.d.driver_number === hover ? 3 : tagFor(m.d) ? 4 : 9);
    const wanted = base.filter((m) => rank(m) < 9).sort((a, b) => rank(a) - rank(b));
    const text = (m: MarkerModel) => `${m.code}${tagFor(m.d) ? ` ${tagFor(m.d)}` : ""}`;
    const tags = (drawable?.timing_lines ?? []).filter((l) => l.x != null && l.y != null)
      .map((l) => lineTagBox(fit.toPx(l.x!, l.y!), l.line));
    const spots = placeLabels(wanted.map((m) => ({ id: m.d.driver_number, x: m.x, y: m.y, w: text(m).length * 6.6 + 4 })),
                              fit.width, fit.height, tags);
    return base.map((m) => {
      const s = spots.get(m.d.driver_number);
      return s ? { ...m, label: { dx: s.x - m.x, dy: s.y - m.y, anchor: s.anchor } } : m;
    }).sort((a, b) => Number(a.selected || a.battle) - Number(b.selected || b.battle));
  }, [fit, drawable, order, moment.rows, moment.driver, selected, battle, hover, focusN]);

  const register = useCallback((n: number, el: SVGGElement | null) => {
    if (el) refs.current.set(n, el); else refs.current.delete(n);
  }, []);
  const pick = useCallback((n: number) => {
    onSelect(n);
    if (shown) onPositionSelect?.(n, new Date(shown.at).toISOString());
  }, [onSelect, onPositionSelect, shown]);
  const onKey = useCallback((n: number, e: KeyboardEvent<SVGGElement>) => {
    const i = order.findIndex((d) => d.driver_number === n);
    const move = (j: number) => {
      const next = order[Math.max(0, Math.min(order.length - 1, j))];
      if (!next) return;
      setFocusN(next.driver_number);
      refs.current.get(next.driver_number)?.focus();
    };
    if (e.key === "ArrowDown" || e.key === "ArrowRight") move(i + 1);
    else if (e.key === "ArrowUp" || e.key === "ArrowLeft") move(i - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(order.length - 1);
    else if (e.key === "Enter" || e.key === " ") pick(n);
    else if (e.key === "Escape") onSelect(null);
    else return;
    e.preventDefault();
  }, [order, pick, onSelect]);

  const tween = playing ? Math.min((windowForRate(rate).stepS * 1000) / rate, 250) : 0;
  const tone = phaseTone(moment.frame.phase);
  const hovered = hover != null ? models.find((m) => m.d.driver_number === hover) ?? null : null;
  const pair = battle ? models.filter((m) => m.battle) : [];
  const empty = !!shown && order.length === 0;
  const activeLine = drawable?.timing_lines.find((l) => l.line === line) ?? null;

  const meta = shown
    ? <><span>positions at {fmtClockTenths(shown.at)}</span>{view.lagging && <span className="sm-lag">positions lag the cursor</span>}</>
    : <span>{view.status === "loading" ? "loading positions" : "no positions"}</span>;

  let body;
  if (view.status === "unavailable") {
    body = (
      <div className="sm-state" role="status">
        <p className="cc-empty-title">Spatial map unavailable</p>
        <p className="cc-empty-why">{view.reason ? REASON_TEXT[view.reason] : "No validated spatial data."}</p>
        {view.reasons.length > 0 && <ul className="sm-reasons">{view.reasons.map((r) => <li key={r}><code>{r}</code></li>)}</ul>}
      </div>
    );
  } else if (view.status === "error") {
    body = <ErrorState title="Spatial positions could not be loaded" message={view.error?.message ?? "Unexpected error."} onRetry={view.retry} />;
  } else if (!drawable || !fit) {
    body = <div className="sm-skeleton" aria-busy="true" aria-label="Loading track" />;
  } else {
    body = (
      <>
        <svg className={`sm-map${reduced ? " is-reduced" : ""}`} width={fit.width} height={fit.height}
             viewBox={`0 0 ${fit.width} ${fit.height}`} role="group"
             aria-label={`Track map, positions at ${shown ? fmtClockTenths(shown.at) : "no time"}`}
             style={{ ["--spatial-tween" as string]: `${reduced ? 0 : tween}ms` }}>
          <CircuitLayer track={drawable} fit={fit} hotSector={hotSector} onSector={setHotSector} />
          <LineLayer track={drawable} fit={fit} active={line} onLine={setLine} />
          {pair.length === 2 && (
            <line className="sm-battle-link" x1={pair[0].x} y1={pair[0].y} x2={pair[1].x} y2={pair[1].y} />
          )}
          <g className="sm-layer-markers">
            {models.map((m) => (
              <Marker key={m.d.driver_number} m={m} register={register} onPick={pick} onKey={onKey} onHover={setHover} />
            ))}
          </g>
          {ghost && <Ghost ghost={ghost} at={fit.toPx(ghost.x, ghost.y)} width={fit.width} />}
        </svg>
        {tone !== "green" && tone !== "neutral" && (
          <p className={`sm-phase sm-phase-${tone}`}>{phaseLabel(moment.frame.phase)} <span>{fmtAsOf(moment.frame)}</span></p>
        )}
        {empty && <p className="sm-note" role="status">No position coverage at this moment</p>}
        {!shown && view.status === "loading" && <p className="sm-note" role="status">Loading positions…</p>}
        {hovered && <Tooltip m={hovered} width={fit.width} />}
      </>
    );
  }

  return (
    <Panel id="cc-map" title="Track map" className="cc-map" meta={meta}
      actions={drawable ? (
        <button type="button" className="cc-btn cc-btn-ghost sm-info-btn" aria-expanded={info} aria-controls="cc-map-info"
                onClick={() => setInfo((v) => !v)}>Map info</button>
      ) : undefined}>
      <div ref={frameRef} className="sm-frame">{body}</div>
      {activeLine && (
        <p className="sm-line-readout cc-mono">
          {activeLine.line} line · p95 {activeLine.dispersion_m?.p95.toFixed(1) ?? "—"} m · n {activeLine.n.toLocaleString("en-US")} crossings
          · measured from official timestamps
        </p>
      )}
      {shown && drawable && <NotOnMap drivers={shown.drivers} moment={moment} />}
      {shown && drawable && <MapTable drivers={shown.drivers} moment={moment} at={shown.at} />}
      {info && drawable && <MapInfo id="cc-map-info" track={drawable} />}
    </Panel>
  );
});
