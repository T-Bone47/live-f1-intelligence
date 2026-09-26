/**
 * Track map companions (Phase 12B): the hover/focus tooltip, the "Not on map"
 * strip for cars without position coverage, and the visually hidden table
 * that states every car's spatial state in words.
 */

import { driverCode, fmtClockTenths } from "../../command/format";
import type { Moment } from "../../command/moment";
import type { DriverState } from "../../spatial/types";
import { DriverChip } from "../command/ui";
import type { MarkerModel } from "./Markers";
import { fmtAge, fmtMetres, gradeWord, stateWords } from "./words";

export function Tooltip({ m, width }: { m: MarkerModel; width: number }) {
  const { d } = m;
  const left = Math.max(4, Math.min(width - 184, m.x + 14));
  return (
    <div className="sm-tooltip" role="tooltip" style={{ left, top: Math.max(4, m.y - 12) }}>
      <p className="sm-tooltip-head"><span className="cc-mono">#{d.driver_number}</span> {m.code}</p>
      <dl className="sm-dl">
        <dt>State</dt><dd>{stateWords(d)}</dd>
        <dt>Lap</dt><dd className="cc-mono">{d.lap_number ?? "—"}</dd>
        <dt>Sector</dt><dd className="cc-mono">{d.sector != null ? `S${d.sector}` : "—"}</dd>
        <dt>Distance</dt><dd className="cc-mono">{fmtMetres(d.distance_m)}</dd>
        <dt>Confidence</dt><dd>{gradeWord(d.confidence)}</dd>
        {d.status === "STALE" && <><dt>Last sample</dt><dd className="cc-mono">{fmtAge(d.age_s)} before</dd></>}
      </dl>
    </div>
  );
}

export function NotOnMap({ drivers, moment }: { drivers: DriverState[]; moment: Moment }) {
  const off = drivers.filter((d) => d.status === "NO_COVERAGE");
  if (off.length === 0) return null;
  return (
    <div className="sm-offmap">
      <span className="cc-eyebrow">Not on map</span>
      <ul>
        {off.map((d) => (
          <li key={d.driver_number}>
            <DriverChip driver={moment.driver.get(d.driver_number)} num={d.driver_number} size="sm" />
            <span className="sm-offmap-why">no coverage</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MapTable({ drivers, moment, at }: { drivers: DriverState[]; moment: Moment; at: number }) {
  return (
    <div className="cc-sr">
      <table>
        <caption>Spatial state of every car at {fmtClockTenths(at)}</caption>
        <thead>
          <tr><th>Car</th><th>Driver</th><th>State</th><th>Lap</th><th>Sector</th><th>Distance</th><th>Confidence</th></tr>
        </thead>
        <tbody>
          {drivers.map((d) => (
            <tr key={d.driver_number}>
              <td>{d.driver_number}</td>
              <td>{driverCode(moment.driver.get(d.driver_number), d.driver_number)}</td>
              <td>{stateWords(d)}</td>
              <td>{d.lap_number ?? "—"}</td>
              <td>{d.sector != null ? `S${d.sector}` : "—"}</td>
              <td>{fmtMetres(d.distance_m)}</td>
              <td>{d.status === "NO_COVERAGE" ? "—" : gradeWord(d.confidence)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
