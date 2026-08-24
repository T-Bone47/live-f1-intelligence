/**
 * "Where Did The Time Go?" — Sector delta visualization
 * Shows S1/S2/S3 time differences between two drivers
 */

import { useEffect, useState } from "react";
import { useSessionState, useDriverSelection, apiGet } from "../../state/store";
import { Panel, Delta, ProvenanceBadge } from "../shared";
import { fmtSec, UNAVAILABLE, sectorStyle } from "../../logic/format";

export function TimeDelta() {
  const st = useSessionState();
  const { selectedDriver, comparisonDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const sessionId = snap?.session_id;

  const [sectorsA, setSectorsA] = useState<any>(null);
  const [sectorsB, setSectorsB] = useState<any>(null);

  useEffect(() => {
    if (!sessionId || !selectedDriver) { setSectorsA(null); return; }
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/sectors/${selectedDriver}`)
      .then((d) => { if (alive) setSectorsA(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [sessionId, selectedDriver]);

  useEffect(() => {
    if (!sessionId || !comparisonDriver) { setSectorsB(null); return; }
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/sectors/${comparisonDriver}`)
      .then((d) => { if (alive) setSectorsB(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [sessionId, comparisonDriver]);

  if (!selectedDriver || !comparisonDriver) return null;
  if (!sectorsA?.available || !sectorsB?.available) return null;

  const sa = sectorsA.sectors ?? {};
  const sb = sectorsB.sectors ?? {};

  const sectorDiffs = [1, 2, 3].map((s) => {
    const aTime = sa[String(s)]?.personal_best_s ?? null;
    const bTime = sb[String(s)]?.personal_best_s ?? null;
    const aCls = sa[String(s)]?.classification;
    const bCls = sb[String(s)]?.classification;
    const delta = aTime != null && bTime != null ? aTime - bTime : null;
    return { sector: s, aTime, bTime, aCls, bCls, delta };
  });

  const totalDelta = sectorDiffs.reduce((sum, s) => {
    if (s.delta == null) return sum;
    return (sum ?? 0) + s.delta;
  }, null as number | null);

  const theoreticalA = sectorsA.theoretical_lap_s;
  const theoreticalB = sectorsB.theoretical_lap_s;
  const theoreticalDelta = theoreticalA != null && theoreticalB != null
    ? theoreticalA - theoreticalB : null;

  return (
    <Panel title="WHERE DID THE TIME GO?"
      actions={<ProvenanceBadge type="DERIVED" />}>
      <div style={{ display: "flex", gap: "var(--sp-3)", justifyContent: "center", padding: "var(--sp-1) 0" }}>
        <span className="mono" style={{ fontWeight: 700, color: "var(--driver-a)" }}>#{selectedDriver}</span>
        <span className="dim">vs</span>
        <span className="mono" style={{ fontWeight: 700, color: "var(--driver-b)" }}>#{comparisonDriver}</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--sp-2)", marginTop: "var(--sp-2)" }}>
        {sectorDiffs.map((s) => (
          <div key={s.sector} style={{
            textAlign: "center", padding: "var(--sp-2)",
            background: "var(--surface-trace)", borderRadius: "var(--radius)",
            border: "1px solid var(--border)",
          }}>
            <span className="metric-label" style={{ color: "var(--sector-purple)" }}>S{s.sector}</span>
            <div style={{ marginTop: "var(--sp-1)" }}>
              <span className="mono text-sm" style={{ color: "var(--driver-a)" }}>
                {fmtSec(s.aTime)}
              </span>
            </div>
            <div>
              <span className="mono text-sm" style={{ color: "var(--driver-b)" }}>
                {fmtSec(s.bTime)}
              </span>
            </div>
            <div style={{ marginTop: "var(--sp-1)" }}>
              <Delta value={s.delta} suffix="s" />
            </div>
          </div>
        ))}
      </div>

      {/* Total + Theoretical */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--sp-2)", marginTop: "var(--sp-2)" }}>
        <div style={{
          textAlign: "center", padding: "var(--sp-2)",
          background: "var(--surface-dim)", borderRadius: "var(--radius)",
          border: "1px solid var(--border)",
        }}>
          <span className="metric-label">TOTAL DELTA</span>
          <div style={{ marginTop: "var(--sp-1)", fontSize: "var(--text-lg)" }}>
            <Delta value={totalDelta} suffix="s" />
          </div>
        </div>
        <div style={{
          textAlign: "center", padding: "var(--sp-2)",
          background: "var(--surface-dim)", borderRadius: "var(--radius)",
          border: "1px solid var(--border)",
        }}>
          <span className="metric-label">THEORETICAL DELTA</span>
          <div style={{ marginTop: "var(--sp-1)", fontSize: "var(--text-lg)" }}>
            <Delta value={theoreticalDelta} suffix="s" />
          </div>
        </div>
      </div>
    </Panel>
  );
}

/**
 * Theoretical Lap display — first-class display of the theoretical best
 */
export function TheoreticalLap() {
  const st = useSessionState();
  const { selectedDriver } = useDriverSelection();
  const snap = st.snapshot as any;
  const sessionId = snap?.session_id;
  const [sectors, setSectors] = useState<any>(null);

  useEffect(() => {
    if (!sessionId || !selectedDriver) { setSectors(null); return; }
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/sectors/${selectedDriver}`)
      .then((d) => { if (alive) setSectors(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [sessionId, selectedDriver]);

  if (!selectedDriver || !sectors?.available) return null;

  const theoretical = sectors.theoretical_lap_s;
  const actual = sectors.personal_best_lap_s;
  const gain = theoretical != null && actual != null ? actual - theoretical : null;

  return (
    <Panel title="THEORETICAL LAP"
      actions={<ProvenanceBadge type="DERIVED" />}>
      <div className="metric-grid" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
        <div className="metric">
          <span className="metric-label">ACTUAL BEST</span>
          <span className="metric-value mono">{fmtSec(actual)}</span>
        </div>
        <div className="metric">
          <span className="metric-label" style={{ color: "var(--sector-purple)" }}>THEORETICAL</span>
          <span className="metric-value mono" style={{ color: "var(--sector-purple)" }}>
            {fmtSec(theoretical)}
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">POTENTIAL GAIN</span>
          <span className="metric-value">
            <Delta value={gain != null ? -gain : null} suffix="s" invert />
          </span>
        </div>
      </div>
    </Panel>
  );
}
