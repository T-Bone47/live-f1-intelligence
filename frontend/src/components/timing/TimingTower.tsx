/**
 * TimingTower 2.0 — Production-grade F1 timing tower
 * Columns: POS Δ DRV TEAM GAP INT LAP LAST BEST S1 S2 S3 TYRE PACE
 * Features: sector coloring, position deltas, pit markers, driver selection,
 * fastest lap highlight, compact/expanded modes
 */

import { memo, useCallback, useState, useEffect, useMemo } from "react";
import { useSessionState, useDriverSelection, apiGet } from "../../state/store";
import { Panel, TyreChip, ConfidenceBadge, TimingValue } from "../shared";
import { fmtSec, fmtGap, fmtInterval, fmtLap, compoundLabel, sectorStyle, teamAbbr, trendArrow, UNAVAILABLE } from "../../logic/format";

type Mode = "expanded" | "compact";

interface SectorData {
  [driver: string]: {
    s1?: { time_s: number; classification: string };
    s2?: { time_s: number; classification: string };
    s3?: { time_s: number; classification: string };
  };
}

export function TimingTower() {
  const st = useSessionState();
  const { selectedDriver, comparisonDriver, selectDriver, selectComparisonDriver } = useDriverSelection();
  const [mode, setMode] = useState<Mode>("expanded");
  const [sectorData, setSectorData] = useState<SectorData>({});

  const snap = st.snapshot as any;
  const board: any[] = snap?.leaderboard ?? [];
  const sessionId = snap?.session_id;
  const fastestLapDriver = snap?.fastest_lap?.driver;

  // Fetch sector data for all drivers periodically
  useEffect(() => {
    if (!sessionId) return;
    let alive = true;

    const fetchSectors = async () => {
      const results: SectorData = {};
      // Batch: get sectors for each driver on the board
      for (const row of board.slice(0, 20)) {
        try {
          const d = await apiGet(`/sessions/${encodeURIComponent(sessionId)}/sectors/${row.driver_number}`);
          if (alive && d?.available) {
            results[row.driver_number] = {
              s1: d.sectors?.["1"] ? { time_s: d.sectors["1"].personal_best_s, classification: d.sectors["1"].classification } : undefined,
              s2: d.sectors?.["2"] ? { time_s: d.sectors["2"].personal_best_s, classification: d.sectors["2"].classification } : undefined,
              s3: d.sectors?.["3"] ? { time_s: d.sectors["3"].personal_best_s, classification: d.sectors["3"].classification } : undefined,
            };
          }
        } catch { /* graceful degradation */ }
      }
      if (alive) setSectorData(results);
    };

    fetchSectors();
    const timer = setInterval(fetchSectors, 8000);
    return () => { alive = false; clearInterval(timer); };
  }, [sessionId, board.length]);

  const handleRowClick = useCallback((num: number, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      // Ctrl+click sets comparison driver
      selectComparisonDriver(comparisonDriver === num ? null : num);
    } else {
      selectDriver(selectedDriver === num ? null : num);
    }
  }, [selectedDriver, comparisonDriver, selectDriver, selectComparisonDriver]);

  const toggleMode = useCallback(() => {
    setMode(m => m === "expanded" ? "compact" : "expanded");
  }, []);

  const isExpanded = mode === "expanded";

  return (
    <Panel title="LIVE TIMING" className="timing-tower-panel"
      actions={
        <button className="preset-btn" onClick={toggleMode}
                title={isExpanded ? "Compact view" : "Expanded view"}>
          {isExpanded ? "▤" : "▦"}
        </button>
      }>
      <div className="timing-tower-wrap">
        {board.length === 0 ? (
          <p className="tt-empty">WAITING FOR TIMING DATA</p>
        ) : (
          <table className="tt-table" role="grid">
            <thead>
              <tr>
                <th className="tt-pos">P</th>
                <th className="tt-delta-pos">Δ</th>
                <th className="tt-driver">DRV</th>
                {isExpanded && <th className="tt-team">TM</th>}
                <th className="tt-gap">GAP</th>
                <th className="tt-int">INT</th>
                <th className="tt-lap">LAP</th>
                <th className="tt-last">LAST</th>
                <th className="tt-best">BEST</th>
                {isExpanded && <>
                  <th className="tt-s1">S1</th>
                  <th className="tt-s2">S2</th>
                  <th className="tt-s3">S3</th>
                </>}
                <th className="tt-tyre">TYRE</th>
                {isExpanded && <th className="tt-pace">PACE</th>}
              </tr>
            </thead>
            <tbody>
              {board.map((row: any) => (
                <TimingRow key={row.driver_number}
                  row={row}
                  isSelected={selectedDriver === row.driver_number}
                  isComparison={comparisonDriver === row.driver_number}
                  isFastestLap={fastestLapDriver === row.driver_number}
                  sectors={sectorData[row.driver_number]}
                  expanded={isExpanded}
                  onClick={handleRowClick}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  );
}

/* ── Single timing row (memo'd for perf) ── */
const TimingRow = memo(function TimingRow({
  row, isSelected, isComparison, isFastestLap, sectors, expanded, onClick,
}: {
  row: any;
  isSelected: boolean;
  isComparison: boolean;
  isFastestLap: boolean;
  sectors: any;
  expanded: boolean;
  onClick: (num: number, e: React.MouseEvent) => void;
}) {
  const cls = [
    "tt-row",
    isSelected ? "selected" : "",
    isComparison ? "comparison" : "",
    isFastestLap ? "fastest-lap" : "",
    row.retired ? "retired" : "",
  ].filter(Boolean).join(" ");

  const s1 = sectors?.s1;
  const s2 = sectors?.s2;
  const s3 = sectors?.s3;

  return (
    <tr className={cls} onClick={(e) => onClick(row.driver_number, e)}
        role="row" aria-selected={isSelected} tabIndex={0}>
      <td className="tt-pos mono">{row.position ?? UNAVAILABLE}</td>
      <td className="tt-delta-pos">
        <PositionDelta position={row.position} driver={row.driver_number} />
      </td>
      <td className="tt-driver">
        <span>{row.driver_number}</span>
        {row.in_pit && <span className="tt-pit-marker">PIT</span>}
      </td>
      {expanded && <td className="tt-team dim">{teamAbbr(row.team_name)}</td>}
      <td className="tt-gap mono">{row.position === 1 ? "" : fmtGap(row)}</td>
      <td className="tt-int mono">{row.position === 1 ? "" : fmtInterval(row.interval_s)}</td>
      <td className="tt-lap mono">{row.lap_number ?? UNAVAILABLE}</td>
      <td className="tt-last mono">{fmtLap(row.last_lap_s)}</td>
      <td className="tt-best mono">{fmtLap(row.personal_best_s)}</td>
      {expanded && <>
        <td className={`tt-s1 ${s1 ? sectorStyle(s1.classification).cssClass : ""}`}>
          {s1 ? fmtSec(s1.time_s) : UNAVAILABLE}
        </td>
        <td className={`tt-s2 ${s2 ? sectorStyle(s2.classification).cssClass : ""}`}>
          {s2 ? fmtSec(s2.time_s) : UNAVAILABLE}
        </td>
        <td className={`tt-s3 ${s3 ? sectorStyle(s3.classification).cssClass : ""}`}>
          {s3 ? fmtSec(s3.time_s) : UNAVAILABLE}
        </td>
      </>}
      <td className="tt-tyre">
        <TyreChip compound={row.compound} age={row.tyre_age} />
      </td>
      {expanded && (
        <td className="tt-pace mono">
          {row.rolling5_s != null ? fmtSec(row.rolling5_s) : UNAVAILABLE}
          {row.pace_trend_s_per_lap != null && (
            <span className="dim" title="Pace trend">{trendArrow(row.pace_trend_s_per_lap)}</span>
          )}
        </td>
      )}
    </tr>
  );
});

/* ── Position delta indicator ── */
function PositionDelta({ position, driver }: { position: number | null; driver: number }) {
  // Static display — actual deltas require tracking previous positions
  // which the WebSocket protocol handles via snapshot diffs.
  // For now, render a stable dash. Position deltas from the backend
  // will be wired when available in the leaderboard payload.
  return <span className="same">-</span>;
}
