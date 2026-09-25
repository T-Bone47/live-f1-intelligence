/**
 * Engineering evidence for one segment: braking, throttle, speed, gear, DRS.
 *
 * Values are the contract's; "A − B" columns show the contract's own
 * difference fields (never a subtraction done here). Offsets are phrased from
 * the contract rule "sign A − B along the lap". A missing channel is said to
 * be missing — never read as "did not brake".
 */

import type { ReactNode } from "react";
import type { Categorical, Segment } from "../../evidence/types";
import type { EvidenceView } from "../../evidence/viewModel";
import {
  fmtBand, fmtDelta, fmtFraction, fmtInt, fmtKph, fmtPct, fmtSignedKph, fmtSignedNum, fmtX,
  offsetPhrase, UNAVAILABLE,
} from "../../evidence/format";
import { phaseText } from "../../evidence/vocabulary";
import { Icon, ResolvableTag } from "./primitives";

type Row = [label: string, a: ReactNode, b: ReactNode, diff?: ReactNode];

function Table({ view, rows, diffHead = "A − B / note" }: { view: EvidenceView; rows: Row[]; diffHead?: string }) {
  return (
    <table className="ewb-etable">
      <thead><tr><th scope="col">Metric</th><th scope="col">#{view.a}</th><th scope="col">#{view.b}</th><th scope="col">{diffHead}</th></tr></thead>
      <tbody>
        {rows.map(([label, a, b, d]) => (
          <tr key={label}><th scope="row">{label}</th><td>{a}</td><td>{b}</td><td>{d ?? ""}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function Group({ title, summary, children, open = true }: { title: string; summary: ReactNode; children: ReactNode; open?: boolean }) {
  return (
    <details className="ewb-egroup" open={open}>
      <summary><Icon name="chevronDown" /><span className="ewb-egroup-title">{title}</span><span className="ewb-egroup-sum">{summary}</span></summary>
      {children}
    </details>
  );
}

function Offset({ view, offset, what, resolvable }: { view: EvidenceView; offset: number | null; what: string; resolvable: boolean }) {
  return <span className="ewb-offset">{offsetPhrase(offset, view.a, what, view.normalized)} <ResolvableTag resolvable={resolvable} /></span>;
}

function categoricalRows(c: Categorical): Row[] {
  const runs = c.runs.length;
  const res = c.runs.filter((r) => r.resolvable).length;
  return [
    ["Minimum", fmtInt(c.min_a), fmtInt(c.min_b)],
    ["Distinct values", c.values_a.join(", ") || UNAVAILABLE, c.values_b.join(", ") || UNAVAILABLE],
    ["Differing fraction", "", "", fmtFraction(c.difference_fraction)],
    ["Difference runs", "", "", `${runs} run${runs === 1 ? "" : "s"}, ${res} resolvable`],
    ["First resolvable", "", "", c.first_resolvable_x == null ? "none" : fmtX(c.first_resolvable_x)],
  ];
}

export function EngineeringEvidence({ view, seg: s }: { view: EvidenceView; seg: Segment }) {
  const ch = view.evidence.comparison;
  const missing = (k: "brake" | "throttle" | "gear" | "drs") => !ch.driver_a.telemetry.channels[k] || !ch.driver_b.telemetry.channels[k];
  const br = s.braking, th = s.throttle, sp = s.speed;

  if (s.direction === "NO_DATA") {
    return <p className="ewb-muted">No engineering evidence: this span has no telemetry coverage.</p>;
  }

  return (
    <div className="ewb-engineering">
      <h3 className="ewb-subhead">Engineering evidence</h3>

      <Group title="Braking" summary={missing("brake") ? "channel missing" : !br ? "no comparison"
        : br.onset_offset_resolvable ? offsetPhrase(br.onset_offset_m, view.a, "brake onset", view.normalized) : "no resolvable onset difference"}>
        {missing("brake") ? <p className="ewb-warn-text">Brake channel missing — absent is not “did not brake”.</p>
          : !br ? <p className="ewb-muted">No braking comparison in this segment.</p> : (
          <>
            {!br.paired && <p className="ewb-warn-text">Braking present in one lap only.</p>}
            <Table view={view} rows={[
              ["Applications", fmtInt(br.applications_a), fmtInt(br.applications_b)],
              ["Onset", fmtX(br.onset_x_a), fmtX(br.onset_x_b), <Offset view={view} offset={br.onset_offset_m} what="brake onset" resolvable={br.onset_offset_resolvable} />],
              ["Release", fmtX(br.release_x_a), fmtX(br.release_x_b), <Offset view={view} offset={br.release_offset_m} what="brake release" resolvable={br.release_offset_resolvable} />],
              ["Peak brake", fmtPct(br.peak_pct_a), fmtPct(br.peak_pct_b), "feed is binary 0/100"],
              ["Speed at onset", fmtKph(br.speed_at_onset_a_kph), fmtKph(br.speed_at_onset_b_kph)],
              ["Braking zone (both)", "", "", `${fmtX(br.zone_start_x)}–${br.zone_end_x.toFixed(3)}`],
            ]} />
          </>
        )}
      </Group>

      <Group title="Throttle" summary={missing("throttle") ? "channel missing" : !th ? "no comparison"
        : th.application_resolvable ? offsetPhrase(th.application_offset_m, view.a, "throttle application", view.normalized)
        : th.full_resolvable ? offsetPhrase(th.full_offset_m, view.a, "full throttle", view.normalized) : "no resolvable offset"}>
        {missing("throttle") ? <p className="ewb-warn-text">Throttle channel missing.</p> : !th ? <p className="ewb-muted">No throttle comparison.</p> : (
          <Table view={view} rows={[
            ["Lift", fmtX(th.lift_x_a), fmtX(th.lift_x_b), <Offset view={view} offset={th.lift_offset_m} what="lift" resolvable={th.lift_resolvable} />],
            ["Application", fmtX(th.application_x_a), fmtX(th.application_x_b), <Offset view={view} offset={th.application_offset_m} what="application" resolvable={th.application_resolvable} />],
            ["Full regained", fmtX(th.full_x_a), fmtX(th.full_x_b), <Offset view={view} offset={th.full_offset_m} what="full throttle" resolvable={th.full_resolvable} />],
            ["Minimum", fmtPct(th.minimum_a_pct), fmtPct(th.minimum_b_pct)],
            ["Full level (per car)", fmtPct(th.full_level_a_pct), fmtPct(th.full_level_b_pct), `modal ${fmtPct(th.full_modal_a_pct)} / ${fmtPct(th.full_modal_b_pct)}`],
            ["Mean difference", "", "", <>{fmtSignedNum(th.mean_throttle_difference_pct, 1)} %{view.hasLimitation("THROTTLE_CALIBRATION_DIFFERS") && <span className="ewb-muted"> · includes calibration</span>}</>],
          ]} />
        )}
      </Group>

      <Group title="Speed" summary={!sp ? "no comparison" : sp.min_speed_resolvable
        ? `minimum ${fmtKph(sp.min_speed_a_kph)} vs ${fmtKph(sp.min_speed_b_kph)}` : "no resolvable minimum-speed difference"}>
        {!sp ? <p className="ewb-muted">No speed comparison.</p> : (
          <Table view={view} rows={[
            ["Minimum", <>{fmtKph(sp.min_speed_a_kph)} <span className="ewb-muted">{fmtX(sp.min_speed_x_a)}</span></>,
              <>{fmtKph(sp.min_speed_b_kph)} <span className="ewb-muted">{fmtX(sp.min_speed_x_b)}</span></>,
              <>{fmtSignedKph(sp.min_speed_difference_kph, 0)} <ResolvableTag resolvable={sp.min_speed_resolvable} /></>],
            ["At segment end", fmtKph(sp.end_speed_a_kph, 1), fmtKph(sp.end_speed_b_kph, 1)],
            ["Mean difference", "", "", fmtSignedKph(sp.mean_difference_kph)],
            ["Range of difference", "", "", `${fmtSignedKph(sp.min_difference_kph)} to ${fmtSignedKph(sp.max_difference_kph)}`],
            ["Divergence onset", "", "", sp.divergence_onset_x == null ? "none beyond alignment error" : `${fmtX(sp.divergence_onset_x)} · ${fmtFraction(sp.divergence_fraction)} of segment`],
          ]} />
        )}
      </Group>

      <Group title="Gear" open={false} summary={missing("gear") || !s.gear.available ? "not available"
        : `minimum ${fmtInt(s.gear.min_a)} vs ${fmtInt(s.gear.min_b)}`}>
        {missing("gear") || !s.gear.available ? <p className="ewb-muted">Gear comparison not available.</p>
          : <><p className="ewb-muted ewb-small">Compared for equality only; gears are never subtracted.</p><Table view={view} rows={categoricalRows(s.gear)} diffHead="Comparison" /></>}
      </Group>

      <Group title="DRS" open={false} summary={missing("drs") || !s.drs.available ? "not available" : `raw codes, ${fmtFraction(s.drs.difference_fraction)} differing`}>
        {missing("drs") || !s.drs.available ? <p className="ewb-muted">DRS comparison not available.</p>
          : <><p className="ewb-warn-text ewb-small">Raw DRS codes; their open/closed meaning is not verified.</p><Table view={view} rows={categoricalRows(s.drs)} diffHead="Comparison" /></>}
      </Group>

      <IntraSegment view={view} seg={s} />
    </div>
  );
}

function IntraSegment({ view, seg: s }: { view: EvidenceView; seg: Segment }) {
  const phases = Array.from(new Set([...Object.keys(s.phase_accumulation_a), ...Object.keys(s.phase_accumulation_b)]));
  const br = s.braking;
  return (
    <Group title="Intra-segment splits" open={false} summary="less certain than the segment total">
      <p className="ewb-warn-text ewb-small">Splits end at changing speed and carry larger alignment uncertainty than the segment total.</p>
      {br && (
        <Table view={view} diffHead="Change · band" rows={[
          ["Before braking", "", "", <>{fmtDelta(br.delta_before_s)} <span className="ewb-muted">{fmtBand(br.band_before_s)}</span></>],
          ["During braking", "", "", <>{fmtDelta(br.delta_during_s)} <span className="ewb-muted">{fmtBand(br.band_during_s)}</span></>],
          ["After braking", "", "", <>{fmtDelta(br.delta_after_s)} <span className="ewb-muted">{fmtBand(br.band_after_s)}</span></>],
          ...(s.throttle ? [["After throttle application", "", "", fmtDelta(s.throttle.delta_after_application_s)] as Row] : []),
        ]} />
      )}
      {phases.length > 0 && (
        <table className="ewb-etable">
          <caption className="ewb-small">Δ change split by each driver's own phase</caption>
          <thead><tr><th scope="col">Phase</th><th scope="col">by #{view.a}'s phase</th><th scope="col">by #{view.b}'s phase</th></tr></thead>
          <tbody>
            {phases.map((p) => (
              <tr key={p}><th scope="row">{phaseText(p)}</th><td>{fmtDelta(s.phase_accumulation_a[p])}</td><td>{fmtDelta(s.phase_accumulation_b[p])}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="ewb-muted ewb-small">Dominant phase (#{view.a}): {s.dominant_phase_a ? phaseText(s.dominant_phase_a) : UNAVAILABLE}</p>
    </Group>
  );
}
