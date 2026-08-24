import { useSessionState, useDriverSelection, useEvents } from "../../state/store";
import { Panel, ProvenanceBadge } from "../shared";
import { fmtSec, UNAVAILABLE } from "../../logic/format";

export function PitAnalytics() {
  const st = useSessionState();
  const { selectedDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const sessionId = snap?.session_id;

  const events = useEvents(sessionId);

  if (!selectedDriver) {
    return (
      <Panel title="Pit Analytics">
        <div className="empty-state">Select a driver to view pit analytics</div>
      </Panel>
    );
  }

  // Filter for PIT_STOP events for the selected driver
  const pitStops = events.filter(
    (e) => e.event_type === "PIT_STOP" && e.drivers?.includes(selectedDriver)
  );

  return (
    <Panel title={`Pit Analytics - Driver ${selectedDriver}`}>
      <ProvenanceBadge level="HIGH" label="F1 SIGNALR" />
      {pitStops.length === 0 ? (
        <div className="empty-state" style={{ padding: "20px", color: "var(--text-dim)" }}>
          No pit stops recorded yet
        </div>
      ) : (
        <div className="pit-analytics-list" style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
          {pitStops.map((stop, i) => (
            <div key={i} className="pit-stop-item" style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              background: "rgba(255, 255, 255, 0.05)", padding: "10px 14px", borderRadius: "6px"
            }}>
              <div>
                <div style={{ color: "var(--text-dim)", fontSize: "0.85rem" }}>STOP {i + 1}</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 600 }}>{new Date(stop.ts).toLocaleTimeString()}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ color: "var(--text-dim)", fontSize: "0.85rem" }}>LANE TIME</div>
                <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--accent-red)" }}>
                  {stop.metrics?.lane_duration_s ? fmtSec(stop.metrics.lane_duration_s) : UNAVAILABLE}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
