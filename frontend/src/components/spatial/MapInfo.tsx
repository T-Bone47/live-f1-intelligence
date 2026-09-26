/**
 * Map information drawer (Phase 12B): where the geometry comes from, what is
 * validated, what is not (each with the contract's own reason), how precisely
 * positions are placed, and the legend. Everything is read from
 * track_reference_v1; nothing is asserted by the UI.
 */

import type { TrackReference } from "../../spatial/types";

const VALIDATED = ["Map", "Sectors", "Timing lines", "Driver position"];
const UNAVAILABLE: [keyof TrackReference["capabilities"], string][] = [
  ["racing_line", "Racing line"], ["corners", "Corners"], ["drs_zones", "DRS zones"], ["pit_lane_geometry", "Pit-lane path"],
];

function Glyph({ kind }: { kind: "dot" | "ring" | "square" | "stale" | "uncertain" | "selected" | "sector" | "line" }) {
  return (
    <svg className="sm-glyph" width={22} height={16} viewBox="-11 -8 22 16" aria-hidden="true">
      {kind === "dot" && <circle className="sm-shape" r={5} />}
      {kind === "ring" && <circle className="sm-shape sm-ring" r={4.5} fill="none" />}
      {kind === "square" && <rect className="sm-shape" x={-4} y={-4} width={8} height={8} />}
      {kind === "stale" && <g opacity={0.5}><circle className="sm-shape" r={5} /></g>}
      {kind === "uncertain" && <><circle className="sm-uncertain" r={6.5} /><circle className="sm-shape" r={4} /></>}
      {kind === "selected" && <><circle className="sm-halo" r={7} /><circle className="sm-shape" r={4} /></>}
      {kind === "sector" && <path className="sm-sector" d="M-10 0H10" />}
      {kind === "line" && <line className="sm-line-tick" x1={0} x2={0} y1={-6} y2={6} />}
    </svg>
  );
}

const LEGEND: [Parameters<typeof Glyph>[0]["kind"], string][] = [
  ["dot", "on the reference line"], ["ring", "OFF - off the reference line"], ["square", "PIT - in the pit lane (no path drawn)"],
  ["stale", "STALE - last sample more than 2 s old"], ["uncertain", "low or no confidence"],
  ["selected", "selected driver or battle pair"], ["sector", "sector path (S1, S2, S3)"],
  ["line", "timing line (FINISH, S1, S2), measured from official timestamps"],
];

export function MapInfo({ id, track }: { id: string; track: TrackReference }) {
  const ref = track.reference;
  const p95 = (line: string) => track.timing_lines.find((l) => l.line === line)?.dispersion_m?.p95;
  return (
    <section id={id} className="sm-info" role="region" aria-label="Map info">
      <div className="sm-info-col">
        <h3 className="cc-eyebrow">Provenance</h3>
        <dl className="sm-dl">
          <dt>Source</dt><dd>OpenF1 location feed, recorded session</dd>
          <dt>Session</dt><dd className="cc-mono">{track.session.session_id}</dd>
          <dt>Contract</dt><dd className="cc-mono">{track.contract_version} · {track.builder_version}</dd>
          <dt>Status</dt><dd>{track.status === "VALIDATED_MAP_SECTOR" ? "Validated for map and sectors" : "Not validated"}</dd>
          <dt>Track id</dt><dd className="cc-mono">{track.track_id}</dd>
          <dt>Reference</dt><dd>{ref ? `#${ref.driver_number}, lap ${ref.lap_number}` : "—"}</dd>
          <dt>Input digest</dt><dd className="cc-mono">{track.provenance.input_digest.slice(0, 16)}…</dd>
          <dt>Frame</dt><dd>feed coordinates, arbitrary origin, undocumented unit - no metric axes</dd>
        </dl>
      </div>
      <div className="sm-info-col">
        <h3 className="cc-eyebrow">Capabilities</h3>
        <ul className="sm-caps">
          {VALIDATED.map((v) => <li key={v} className="sm-cap-ok"><span>{v}</span> <em>validated</em></li>)}
        </ul>
        <ul className="sm-caps sm-unavailable">
          {UNAVAILABLE.map(([k, name]) => (
            <li key={k}><span>{name}</span> <em>unavailable</em><p>{track.capabilities[k].reason}</p></li>
          ))}
        </ul>
        <h3 className="cc-eyebrow">Precision</h3>
        <p className="sm-small">
          Timing lines land within p95{" "}
          <span className="cc-mono">
            {["FINISH", "S1", "S2"].map((l) => `${l} ${p95(l)?.toFixed(1) ?? "—"} m`).join(" · ")}
          </span>{" "}
          of their measured position. <span className="sm-unavailable">No corner-level distances.</span>
        </p>
      </div>
      <div className="sm-info-col">
        <h3 className="cc-eyebrow">Legend</h3>
        <ul className="sm-legend">
          {LEGEND.map(([k, text]) => <li key={k}><Glyph kind={k} /><span>{text}</span></li>)}
        </ul>
      </div>
    </section>
  );
}
