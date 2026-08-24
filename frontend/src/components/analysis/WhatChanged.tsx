/**
 * What Changed — Highlights the most significant events in the last 5 laps
 */

import { useSessionState } from "../../state/store";
import { Panel, ProvenanceBadge } from "../shared";
import { eventIcon, fmtTime } from "../../logic/format";

export function WhatChanged() {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const events: any[] = snap?.recent_events ?? [];
  const currentLap = snap?.current_lap ?? 0;

  // Filter events from the last 5 laps
  // Assuming events have a lap property, or just take the last N significant events
  // We'll filter by significance (e.g., overtakes, pit stops, flags)
  const significantTypes = [
    "OVERTAKE", "PIT_STOP", "SAFETY_CAR", "VSC", "RED_FLAG",
    "FASTEST_LAP_CHANGE", "STRATEGY_DEVIATION", "WEATHER_CHANGE"
  ];

  const recent = events
    .filter((e: any) => significantTypes.includes(e.event_type ?? e.type ?? ""))
    .slice(-10) // Limit to the last 10 significant events
    .reverse();

  return (
    <Panel title="WHAT CHANGED (RECENT)"
      actions={<ProvenanceBadge type="DERIVED" />}>
      {recent.length === 0 ? (
        <p className="dim text-sm uppercase">NO SIGNIFICANT RECENT EVENTS</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-2)" }}>
          {recent.map((ev, i) => (
            <div key={i} style={{
              display: "flex", alignItems: "flex-start", gap: "var(--sp-2)",
              padding: "var(--sp-2)", background: "var(--surface-dim)",
              borderRadius: "var(--radius)", border: "1px solid var(--border)",
            }}>
              <span style={{ fontSize: "var(--text-lg)" }}>
                {eventIcon(ev.event_type ?? ev.type ?? "")}
              </span>
              <div style={{ display: "flex", flexDirection: "column" }}>
                <span className="mono dim text-xs">{fmtTime(ev.ts ?? ev.timestamp)}</span>
                <span className="text-sm">{ev.description ?? ev.message ?? ev.event_type}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
