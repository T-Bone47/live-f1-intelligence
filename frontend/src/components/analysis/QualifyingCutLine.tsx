import { useSessionState } from "../../state/store";
import { Panel, ProvenanceBadge } from "../shared";
import { fmtSec, UNAVAILABLE } from "../../logic/format";

export function QualifyingCutLine() {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const board: any[] = snap?.leaderboard ?? [];
  const phase = snap?.phase?.toUpperCase() || "";

  if (snap?.profile !== "QUALIFYING") {
    return null; // Only show in qualifying sessions
  }

  // Determine the cut position based on the session phase
  let cutPos = 15; // Default for Q1
  if (phase.includes("Q2")) cutPos = 10;
  if (phase.includes("Q3")) cutPos = 0; // No cut in Q3

  if (cutPos === 0 || board.length === 0) {
    return null;
  }

  // Find the driver at the cut line (the bubble boy)
  const bubbleDriver = board.find((r) => r.position === cutPos);
  const bubbleTime = bubbleDriver?.personal_best_s;

  return (
    <Panel title={`Qualifying Cut Line - ${phase || "Q"}`}>
      <ProvenanceBadge level="HIGH" label="F1 SIGNALR" />
      <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text-dim)", fontSize: "0.8rem", paddingBottom: "4px" }}>
          <span>POS</span>
          <span>DRV</span>
          <span style={{ textAlign: "right" }}>BEST</span>
          <span style={{ textAlign: "right" }}>TO CUT</span>
        </div>
        
        {board.filter(r => r.position >= cutPos - 3 && r.position <= cutPos + 3).map((r) => {
          const isAtRisk = r.position > cutPos;
          const diffToCut = bubbleTime && r.personal_best_s ? r.personal_best_s - bubbleTime : null;
          
          return (
            <div key={r.driver_number} style={{ 
              display: "flex", justifyContent: "space-between", padding: "6px 8px", 
              alignItems: "center",
              background: isAtRisk ? "rgba(239, 68, 68, 0.1)" : "rgba(255, 255, 255, 0.05)",
              borderLeft: isAtRisk ? "2px solid var(--accent-red)" : "2px solid transparent",
              borderRadius: "4px"
            }}>
              <span style={{ width: "30px", fontWeight: r.position === cutPos ? 700 : 400, color: r.position === cutPos ? "var(--text-bright)" : "var(--text-dim)" }}>
                P{r.position}
              </span>
              <span style={{ width: "40px", fontWeight: 600 }}>{r.driver_number}</span>
              <span style={{ width: "80px", textAlign: "right", fontFamily: "var(--font-mono)" }}>
                {r.personal_best_s ? fmtSec(r.personal_best_s) : UNAVAILABLE}
              </span>
              <span style={{ width: "60px", textAlign: "right", fontFamily: "var(--font-mono)", color: isAtRisk ? "var(--accent-red)" : "var(--text-bright)" }}>
                {diffToCut !== null ? `+${diffToCut.toFixed(3)}` : ""}
              </span>
            </div>
          );
        })}
        <div style={{
          marginTop: "8px", borderTop: "1px dashed var(--accent-red)", paddingTop: "8px",
          textAlign: "center", fontSize: "0.85rem", color: "var(--text-dim)"
        }}>
          Top {cutPos} advance to the next session
        </div>
      </div>
    </Panel>
  );
}
