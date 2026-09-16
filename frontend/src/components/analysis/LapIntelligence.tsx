import { useDriverSelection } from "../../state/store";
import { Panel } from "../shared";

export function LapIntelligence() {
  const { selectedDriver } = useDriverSelection();

  if (!selectedDriver) {
    return (
      <Panel title="Lap Intelligence">
        <div className="empty-state">Select a driver to view lap intelligence</div>
      </Panel>
    );
  }

  // NOTE: no backend endpoint currently returns a per-lap sector history for
  // a driver. /pace/{driver} returns rolling averages (rolling_3_s,
  // rolling_5_s, rolling_10_s, median_s, trend_s_per_lap), not a lap list,
  // and /sectors/{driver} returns only personal-best + last-lap + theoretical,
  // not a history. Rather than fabricate rows or crash trying to iterate an
  // aggregate object, this panel stays honest about not having a source yet.
  return (
    <Panel title={`Lap Intelligence - Driver ${selectedDriver}`}>
      <div className="empty-state" style={{ padding: "20px", color: "var(--text-dim)" }}>
        Per-lap sector breakdown needs a dedicated backend endpoint (recent
        laps with S1/S2/S3 + classification per lap) — not available yet.
      </div>
    </Panel>
  );
}
