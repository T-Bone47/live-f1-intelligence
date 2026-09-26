/**
 * Race control (Phase 11): official messages up to the cursor, newest first,
 * verbatim. Icons and filters come from each message's own flag/text; no
 * message is interpreted or linked to an outcome. Selecting a message moves
 * the session cursor to the first frame that includes it.
 *
 * "Derived" lists the backend's own session events (class C): state changes,
 * fastest-lap changes and pit-stop records.
 */

import { useMemo, useState } from "react";
import { RC_FILTERS, driverCode, fmtClockUtc, fmtLapTime, phaseLabel, rcKind, type RcKind } from "../../command/format";
import type { Moment } from "../../command/moment";
import type { RaceControlMessage, TimelineEvent } from "../../command/types";
import { Badge, EmptyState, Icon, Panel, type IconName } from "./ui";

const KIND_ICON: Record<RcKind, IconName> = {
  red: "flag", yellow: "flag", clear: "flag", green: "flag", blue: "flag", sc: "alert",
  chequered: "flag", incident: "info", limits: "timer", session: "radio", info: "list",
};

const DERIVED_TYPES = new Set(["SESSION_STATE_CHANGE", "FASTEST_LAP_CHANGE", "PIT_STOP", "VSC", "RED_FLAG", "SAFETY_CAR"]);

function derivedText(e: TimelineEvent, moment: Moment): string {
  const who = e.drivers.map((d) => driverCode(moment.driver.get(d), d)).join(", ");
  const m = e.metrics;
  if (e.event_type === "SESSION_STATE_CHANGE") return `Session state ${phaseLabel(String(m.from))} → ${phaseLabel(String(m.to))}`;
  if (e.event_type === "FASTEST_LAP_CHANGE") return `Fastest lap: ${who} ${fmtLapTime(m.duration_s as number)} (lap ${m.lap})`;
  if (e.event_type === "PIT_STOP") return `Pit stop record: ${who}`;
  return `${e.event_type.replace(/_/g, " ")}${who ? `: ${who}` : ""}`;
}

export function RaceControlPanel({ moment, selectedKey, onSelect }: {
  moment: Moment; selectedKey: string | null;
  onSelect: (key: string | null, frameIndex?: number) => void;
}) {
  const [filter, setFilter] = useState("key");
  const [source, setSource] = useState<"official" | "derived">("official");
  const kinds = RC_FILTERS.find((f) => f.id === filter)?.kinds ?? null;
  const messages = useMemo(() => [...moment.raceControl].reverse()
    .filter((m) => !kinds || kinds.includes(rcKind(m))), [moment.raceControl, kinds]);
  const derived = useMemo(() => [...moment.events].reverse()
    .filter((e) => DERIVED_TYPES.has(e.event_type)), [moment.events]);

  return (
    <Panel id="cc-racecontrol" title="Race control" className="cc-rc"
      meta={<span>{moment.raceControl.length} messages up to this lap</span>}
      actions={
        <div className="cc-seg" role="group" aria-label="Source">
          <button type="button" className="cc-seg-btn" aria-pressed={source === "official"} onClick={() => setSource("official")}>Official</button>
          <button type="button" className="cc-seg-btn" aria-pressed={source === "derived"} onClick={() => setSource("derived")}>Derived</button>
        </div>
      }>
      {source === "official" && (
        <>
          <div className="cc-chips" role="group" aria-label="Filter messages">
            {RC_FILTERS.map((f) => (
              <button key={f.id} type="button" className="cc-chip" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                {f.label}
              </button>
            ))}
          </div>
          {messages.length === 0 ? (
            <EmptyState title="No messages" why="Race control sent no message of this kind up to this lap." />
          ) : (
            <ol className="cc-rc-list">
              {messages.map((m: RaceControlMessage) => {
                const kind = rcKind(m);
                const key = m.rcm_key ?? `${m.ts}-${m.message}`;
                const on = key === selectedKey;
                const fresh = m.frame_index === moment.index;
                return (
                  <li key={key}>
                    <button type="button" className={`cc-rc-item cc-rc-${kind}${on ? " is-selected" : ""}${fresh ? " is-fresh" : ""}`}
                            aria-pressed={on} onClick={() => onSelect(on ? null : key, on ? undefined : m.frame_index)}>
                      <span className="cc-rc-icon"><Icon name={KIND_ICON[kind]} size={13} /></span>
                      <span className="cc-rc-meta">
                        <span className="cc-rc-lap">L{m.lap_number ?? "—"}</span>
                        <span className="cc-rc-time">{fmtClockUtc(m.ts)}</span>
                      </span>
                      <span className="cc-rc-msg">{m.message ?? "—"}</span>
                      {fresh && <span className="cc-sr">new at this lap</span>}
                    </button>
                    {on && (
                      <dl className="cc-rc-detail">
                        <div><dt className="cc-label">Category</dt><dd>{m.category ?? "—"}</dd></div>
                        <div><dt className="cc-label">Flag</dt><dd>{m.flag ?? "—"}</dd></div>
                        <div><dt className="cc-label">Scope</dt><dd>{m.scope ?? "—"}{m.marshal_sector != null ? ` · marshal sector ${m.marshal_sector}` : ""}</dd></div>
                        <div><dt className="cc-label">Car</dt><dd>{m.driver_number != null ? driverCode(moment.driver.get(m.driver_number), m.driver_number) : "—"}</dd></div>
                      </dl>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
          <p className="cc-small cc-muted cc-pad"><Badge tone="official">B OFFICIAL</Badge> verbatim. Marshal sectors are not timing sectors.</p>
        </>
      )}
      {source === "derived" && (
        derived.length === 0 ? (
          <EmptyState title="No derived events" why="The analysis engine raised no session-level event up to this lap." />
        ) : (
          <>
            <ol className="cc-rc-list">
              {derived.map((e) => (
                <li key={e.event_key}>
                  <button type="button" className="cc-rc-item cc-rc-info" onClick={() => onSelect(e.event_key, e.frame_index)}>
                    <span className="cc-rc-icon"><Icon name={e.event_type === "PIT_STOP" ? "wrench" : "gauge"} size={13} /></span>
                    <span className="cc-rc-meta"><span className="cc-rc-time">{fmtClockUtc(e.timestamp)}</span></span>
                    <span className="cc-rc-msg">{derivedText(e, moment)}</span>
                  </button>
                </li>
              ))}
            </ol>
            <p className="cc-small cc-muted cc-pad"><Badge tone="derived">C DERIVED</Badge> by the analysis engine from official data.</p>
          </>
        )
      )}
    </Panel>
  );
}
