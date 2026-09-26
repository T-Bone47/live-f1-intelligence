/**
 * One marker per car the backend positions (Phase 12B). The marker sits at
 * the contract's x/y; its shape says the state (dot on the reference, ring off
 * it, square in the pit lane), its colour is the car's team colour only, and
 * every state is also in words (tag, tooltip, accessible name).
 */

import { memo, type KeyboardEvent } from "react";
import type { DriverState } from "../../spatial/types";
import { markerName, tagFor, uncertain } from "./words";

export interface MarkerModel {
  d: DriverState;
  x: number;
  y: number;
  code: string;
  colour: string;
  selected: boolean;
  battle: boolean;
  focusable: boolean;
  /** Label offset relative to the marker, when the label is shown. */
  label: { dx: number; dy: number; anchor: "start" | "end" } | null;
}

export const Marker = memo(function Marker({ m, register, onPick, onKey, onHover }: {
  m: MarkerModel;
  register: (n: number, el: SVGGElement | null) => void;
  onPick: (n: number) => void;
  onKey: (n: number, e: KeyboardEvent<SVGGElement>) => void;
  onHover: (n: number | null) => void;
}) {
  const { d } = m;
  const tag = tagFor(d);
  const cls = ["sm-marker", d.status === "STALE" && "is-stale", d.flag === "OFF_REFERENCE" && "is-off",
               d.flag === "PIT_LANE" && "is-pit", uncertain(d) && "is-uncertain", m.selected && "is-selected",
               m.battle && "is-battle"].filter(Boolean).join(" ");
  const n = d.driver_number;
  return (
    <g ref={(el) => register(n, el)} className={cls} data-driver={n} data-status={d.status} data-flag={d.flag ?? ""}
       style={{ transform: `translate(${m.x.toFixed(1)}px, ${m.y.toFixed(1)}px)` }}
       role="button" tabIndex={m.focusable ? 0 : -1} aria-pressed={m.selected} aria-label={markerName(m.code, d)}
       onClick={() => onPick(n)} onKeyDown={(e) => onKey(n, e)}
       onMouseEnter={() => onHover(n)} onMouseLeave={() => onHover(null)}
       onFocus={() => onHover(n)} onBlur={() => onHover(null)}>
      <circle className="sm-focus" r={13} />
      {(m.selected || m.battle) && <circle className="sm-halo" r={11} />}
      {uncertain(d) && <circle className="sm-uncertain" r={8.5} />}
      {d.flag === "PIT_LANE" ? (
        <rect className="sm-shape sm-square" x={-4} y={-4} width={8} height={8} fill={m.colour} />
      ) : d.flag === "OFF_REFERENCE" ? (
        <circle className="sm-shape sm-ring" r={4.5} fill="none" stroke={m.colour} />
      ) : (
        <circle className="sm-shape sm-dot" r={5} fill={m.colour} />
      )}
      {d.status === "STALE" && (
        <g className="sm-clock" transform="translate(7 -7)" aria-hidden="true">
          <circle r={3.2} />
          <path d="M0 -1.8V0H1.4" />
        </g>
      )}
      {m.label && (
        <text className="sm-label" data-driver={n} x={m.label.dx} y={m.label.dy} textAnchor={m.label.anchor}>
          {m.code}{tag && <tspan className="sm-tag">{` ${tag}`}</tspan>}
        </text>
      )}
    </g>
  );
});
