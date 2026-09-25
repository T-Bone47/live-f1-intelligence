/**
 * Comparison header: who, which laps, the official lap delta (class B) and
 * the engine delta at the last covered point (class C), shown side by side
 * and never merged.
 */

import type { DriverLap } from "../../evidence/types";
import type { EvidenceView } from "../../evidence/viewModel";
import { aheadOf, fmtDelta, fmtLapTime, fmtMetres, fmtX, UNAVAILABLE } from "../../evidence/format";
import { ALIGNMENT_TEXT, UNCERTAINTY_SOURCE_TEXT } from "../../evidence/vocabulary";
import { ClassBadge, ConfidenceTag, DriverTag } from "./primitives";

const CHANNELS = ["brake", "throttle", "gear", "drs"] as const;

function DriverCard({ side, lap }: { side: "A" | "B"; lap: DriverLap }) {
  const t = lap.telemetry;
  const missing = CHANNELS.filter((c) => !t.channels[c]);
  return (
    <div className={`ewb-dcard ewb-dcard-${side.toLowerCase()}`}>
      <div className="ewb-dcard-top">
        <DriverTag side={side} number={lap.driver_number} />
        <span className="ewb-label">Lap {lap.lap_number}</span>
      </div>
      <p className="ewb-laptime" aria-label={`Lap time ${fmtLapTime(lap.lap_duration_s)}`}>
        {fmtLapTime(lap.lap_duration_s)}
      </p>
      <p className="ewb-dcard-meta">
        <ConfidenceTag level={t.confidence} />
        <span>{t.sample_count} samples</span>
        <span>coverage {fmtX(t.x_first)}–{t.x_last == null ? UNAVAILABLE : t.x_last.toFixed(3)}</span>
        {!t.complete && <span className="ewb-warn-text">window incomplete</span>}
        {missing.length > 0 && <span className="ewb-warn-text">missing: {missing.join(", ")}</span>}
      </p>
    </div>
  );
}

export function ComparisonHeader({ view }: { view: EvidenceView }) {
  const { evidence: ev, a, b, normalized } = view;
  const c = ev.comparison;
  const s = ev.source;
  const lapAhead = aheadOf(c.lap_delta_s, a, b);
  const engineAhead = aheadOf(c.engine_delta_last_covered_s, a, b);
  const sideClass = c.lap_delta_s == null ? "" : c.lap_delta_s < 0 ? "ewb-tone-a" : c.lap_delta_s > 0 ? "ewb-tone-b" : "";

  return (
    <section className="ewb-summary" aria-label="Comparison summary">
      <p className="ewb-context">
        <span>{s.circuit ?? "Circuit not recorded"}</span>
        <span>{s.season ?? "Season not recorded"}</span>
        <span>{s.session_type ?? "Session type not recorded"}</span>
        <span className="ewb-mono">{s.session_id}</span>
        <span>{s.event ?? "Event not recorded"}</span>
        <span>provider {s.provider ?? "not recorded"}</span>
      </p>

      <div className="ewb-summary-grid">
        <DriverCard side="A" lap={c.driver_a} />

        <div className="ewb-keyfig">
          <p className="ewb-eyebrow">Official lap Δ <ClassBadge cls={c.lap_delta_provenance_class} /></p>
          <p className={`ewb-keyfig-value ${sideClass}`}>{fmtDelta(c.lap_delta_s)}</p>
          <p className="ewb-keyfig-sub">{lapAhead ?? "Official lap delta unavailable"}</p>
          <dl className="ewb-keyfig-engine">
            <dt>Engine Δ at {fmtX(c.last_covered_x)} <ClassBadge cls={c.engine_delta_last_covered_s == null ? "F" : "C"} /></dt>
            <dd className="ewb-mono">{fmtDelta(c.engine_delta_last_covered_s)}{engineAhead ? ` · ${engineAhead}` : ""}</dd>
          </dl>
          <p className="ewb-sign">Δt = elapsed A − elapsed B · negative means A is ahead</p>
        </div>

        <DriverCard side="B" lap={c.driver_b} />
      </div>

      <dl className="ewb-alignment">
        <div><dt>Alignment</dt><dd>{ALIGNMENT_TEXT[c.alignment.mode]}</dd></div>
        <div>
          <dt>Misalignment bound E</dt>
          <dd className="ewb-mono">±{fmtMetres(c.alignment.misalignment_bound_m, normalized, 2)}</dd>
        </div>
        <div><dt>Bound source</dt><dd>{UNCERTAINTY_SOURCE_TEXT[c.alignment.uncertainty_source] ?? c.alignment.uncertainty_source}</dd></div>
        <div>
          <dt>Lap length</dt>
          <dd><span className="ewb-mono">{fmtMetres(c.lap_length.m, false)}</span> <span className="ewb-cite">cited: {c.lap_length.source}</span></dd>
        </div>
        <div><dt>Comparison</dt><dd><ConfidenceTag level={c.telemetry_confidence} prefix="Confidence" /></dd></div>
        <div><dt>Contract</dt><dd><span className="ewb-valid">{ev.contract_version} · validated by backend</span></dd></div>
      </dl>
    </section>
  );
}
