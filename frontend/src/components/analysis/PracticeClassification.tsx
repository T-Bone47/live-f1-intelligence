import { useSessionState } from "../../state/store";
import { Panel, ProvenanceBadge } from "../shared";
import { compoundLabel, fmtSec, UNAVAILABLE } from "../../logic/format";

export function PracticeClassification() {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const board: any[] = snap?.leaderboard ?? [];

  if (snap?.profile !== "PRACTICE") {
    return null; // Only show in practice sessions
  }

  // Filter out drivers who are in the pit
  const onTrack = board.filter((d) => !d.in_pit);

  // Separate into fast laps vs long runs (simple heuristic based on tyre age and pace trend)
  const shortRuns = onTrack.filter((d) => (d.tyre_age ?? 0) < 5);
  const longRuns = onTrack.filter((d) => (d.tyre_age ?? 0) >= 5);

  return (
    <Panel title="Practice Session Classification">
      <ProvenanceBadge level="HIGH" label="F1 SIGNALR" />
      <div style={{ marginTop: "12px", display: "flex", gap: "16px" }}>
        
        <div style={{ flex: 1 }}>
          <div style={{ borderBottom: "1px solid rgba(255,255,255,0.1)", paddingBottom: "4px", marginBottom: "8px", fontWeight: 600, color: "var(--accent-blue)" }}>
            QUALIFYING SIMULATIONS
          </div>
          {shortRuns.length === 0 ? (
            <div className="dim" style={{ fontSize: "0.85rem" }}>No active short runs</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              {shortRuns.map(d => (
                <div key={d.driver_number} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem" }}>
                  <span style={{ fontWeight: 600 }}>{d.driver_number}</span>
                  <span className="dim">Tyres: {compoundLabel(d.compound)} ({d.tyre_age}L)</span>
                  <span style={{ fontFamily: "var(--font-mono)" }}>{d.last_lap_s ? fmtSec(d.last_lap_s) : UNAVAILABLE}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ flex: 1, borderLeft: "1px solid rgba(255,255,255,0.1)", paddingLeft: "16px" }}>
          <div style={{ borderBottom: "1px solid rgba(255,255,255,0.1)", paddingBottom: "4px", marginBottom: "8px", fontWeight: 600, color: "var(--accent-green)" }}>
            RACE SIMULATIONS
          </div>
          {longRuns.length === 0 ? (
            <div className="dim" style={{ fontSize: "0.85rem" }}>No active long runs</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              {longRuns.map(d => (
                <div key={d.driver_number} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem" }}>
                  <span style={{ fontWeight: 600 }}>{d.driver_number}</span>
                  <span className="dim">Tyres: {compoundLabel(d.compound)} ({d.tyre_age}L)</span>
                  <span style={{ fontFamily: "var(--font-mono)" }}>{d.rolling5_s ? fmtSec(d.rolling5_s) : UNAVAILABLE}</span>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </Panel>
  );
}
