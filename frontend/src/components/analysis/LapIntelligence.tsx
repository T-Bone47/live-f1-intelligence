import { useSessionState, useDriverSelection, usePace } from "../../state/store";
import { Panel, ProvenanceBadge } from "../shared";
import { fmtSec, UNAVAILABLE, sectorStyle } from "../../logic/format";

export function LapIntelligence() {
  const st = useSessionState();
  const { selectedDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const sessionId = snap?.session_id;

  const pace = usePace(sessionId, selectedDriver);

  if (!selectedDriver) {
    return (
      <Panel title="Lap Intelligence">
        <div className="empty-state">Select a driver to view lap intelligence</div>
      </Panel>
    );
  }

  // Get last 5 laps
  const laps = pace ? [...pace].reverse().slice(0, 5) : [];

  return (
    <Panel title={`Lap Intelligence - Driver ${selectedDriver}`}>
      <ProvenanceBadge level="HIGH" label="F1 SIGNALR" />
      {laps.length === 0 ? (
        <div className="empty-state" style={{ padding: "20px", color: "var(--text-dim)" }}>
          Waiting for lap data...
        </div>
      ) : (
        <div className="lap-intelligence-list" style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "6px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text-dim)", fontSize: "0.8rem", paddingBottom: "4px", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
            <span style={{ width: "40px" }}>LAP</span>
            <span style={{ width: "80px", textAlign: "right" }}>TIME</span>
            <span style={{ width: "50px", textAlign: "right" }}>S1</span>
            <span style={{ width: "50px", textAlign: "right" }}>S2</span>
            <span style={{ width: "50px", textAlign: "right" }}>S3</span>
          </div>
          {laps.map((l: any, i: number) => {
            const t = l.lap_time_s;
            const s1 = l.s1_s;
            const s2 = l.s2_s;
            const s3 = l.s3_s;
            return (
              <div key={l.lap_number || i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", alignItems: "center" }}>
                <span style={{ width: "40px", color: "var(--text-dim)" }}>{l.lap_number}</span>
                <span style={{ width: "80px", textAlign: "right", fontFamily: "var(--font-mono)", fontWeight: 600 }}>{t ? fmtSec(t) : UNAVAILABLE}</span>
                <span className={sectorStyle(l.s1_pb, l.s1_ob)} style={{ width: "50px", textAlign: "right", fontFamily: "var(--font-mono)" }}>{s1 ? s1.toFixed(3) : UNAVAILABLE}</span>
                <span className={sectorStyle(l.s2_pb, l.s2_ob)} style={{ width: "50px", textAlign: "right", fontFamily: "var(--font-mono)" }}>{s2 ? s2.toFixed(3) : UNAVAILABLE}</span>
                <span className={sectorStyle(l.s3_pb, l.s3_ob)} style={{ width: "50px", textAlign: "right", fontFamily: "var(--font-mono)" }}>{s3 ? s3.toFixed(3) : UNAVAILABLE}</span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
