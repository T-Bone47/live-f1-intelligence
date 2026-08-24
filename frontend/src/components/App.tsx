/**
 * App.tsx — LIVE F1 INTELLIGENCE
 * Production Pit Wall Layout
 *
 * Shell: Session Header → Status Ribbon → Nav Rail → Main Content
 * Grid:  3-column asymmetric (timing | main | intel)
 * Modes: RACE CMD | QUALI | TELEMETRY | STRATEGY | DRIVER FOCUS | MINIMAL
 */

import { useState, useMemo, useCallback } from "react";
import {
  useSessionState, useDriverSelection,
} from "../state/store";
import {
  StatusBadge, StatusRibbon, NavRail, DataFreshness,
} from "./shared";

// Components
import { TimingTower } from "./timing/TimingTower";
import { TelemetryLab } from "./telemetry/TelemetryLab";
import {
  RacePicture, BattleRadar, WeatherStrip,
  StrategyBoard, CircuitMap, RCFeed, SectorIntel,
} from "./panels/Panels";
import { AIConsole } from "./ai/AIConsole";
import { TyreStrategyTimeline, DegradationDetail, PaceComparison } from "./tyres/TyreTimeline";
import { TimeDelta, TheoreticalLap } from "./analysis/TimeDelta";
import { WhatChanged } from "./analysis/WhatChanged";
import { PitAnalytics } from "./analysis/PitAnalytics";
import { LapIntelligence } from "./analysis/LapIntelligence";
import { QualifyingCutLine } from "./analysis/QualifyingCutLine";
import { PracticeClassification } from "./analysis/PracticeClassification";

type Preset = "race" | "qualifying" | "telemetry" | "strategy" | "focus" | "minimal";

const PRESETS: { id: Preset; label: string }[] = [
  { id: "race",       label: "RACE CMD" },
  { id: "qualifying", label: "QUALI" },
  { id: "telemetry",  label: "TELEMETRY" },
  { id: "strategy",   label: "STRATEGY" },
  { id: "focus",      label: "DRIVER FOCUS" },
  { id: "minimal",    label: "MINIMAL" },
];

export function App() {
  const st = useSessionState();
  const { selectedDriver, comparisonDriver } = useDriverSelection();
  const snap = st.snapshot as any;

  // Auto-detect session mode
  const profile = snap?.profile ?? snap?.session_type ?? "";
  const autoPreset: Preset = useMemo(() => {
    if (profile === "QUALIFYING") return "qualifying";
    if (profile === "PRACTICE") return "telemetry";
    return "race";
  }, [profile]);

  const [preset, setPreset] = useState<Preset>("race");
  const activePreset = preset;

  // Session info
  const phase = snap?.phase ?? "";
  const circuit = snap?.circuit_short_name ?? "";
  const sessionType = snap?.session_type ?? snap?.profile ?? "";
  const currentLap = snap?.current_lap;
  const weather = snap?.weather;
  const trackFlag = snap?.track_flag ?? phase;

  // Data freshness
  const lastUpdate = st.seq;

  const [navActive, setNavActive] = useState("timing");

  return (
    <div className="app">
      {/* ── Session Header ── */}
      <header className="session-header" role="banner">
        <div className="header-left">
          <StatusBadge status={st.status} />
          <strong className="product-name">F1 INTELLIGENCE</strong>
          <span className="session-meta">
            {snap?.country_code && <>
              <span>{snap.country_code}</span>
              <span className="sep">|</span>
            </>}
            {circuit && <>
              <span>{circuit.toUpperCase()}</span>
              <span className="sep">|</span>
            </>}
            {sessionType && <>
              <span>{sessionType}</span>
              <span className="sep">|</span>
            </>}
            {currentLap != null && <span>LAP {currentLap}</span>}
          </span>
        </div>

        <div className="header-center">
          <div className="preset-bar">
            {PRESETS.map((p) => (
              <button key={p.id}
                className={`preset-btn ${activePreset === p.id ? "active" : ""}`}
                onClick={() => setPreset(p.id)}>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="header-right">
          {/* Race control banner */}
          {["RED_FLAG", "SAFETY_CAR", "VSC"].includes(phase) && (
            <span className={`rc-banner rc-${phase.toLowerCase()}`} role="alert">
              {phase.replace(/_/g, " ")}
            </span>
          )}

          {weather?.air_temp_c != null && (
            <span className="hdr-item">
              <span className="hdr-label">AIR</span>
              <span className="hdr-value">{weather.air_temp_c.toFixed(0)}°C</span>
            </span>
          )}
          {weather?.track_temp_c != null && (
            <span className="hdr-item">
              <span className="hdr-label">TRK</span>
              <span className="hdr-value">{weather.track_temp_c.toFixed(0)}°C</span>
            </span>
          )}

          <DataFreshness ageMs={st.status === "LIVE" || st.status === "REPLAY" ? 1000 : st.status === "DEGRADED" ? 5000 : null} />

          <span className="hdr-item">
            <span className="hdr-label">SEQ</span>
            <span className="hdr-value">{lastUpdate}</span>
          </span>
        </div>
      </header>

      {/* ── Status Ribbon ── */}
      <StatusRibbon phase={trackFlag} status={st.status} />

      {/* ── Nav Rail ── */}
      <NavRail active={navActive} onNav={setNavActive} />

      {/* ── Main Content ── */}
      <div className="main-content">
        {/* Race Picture (only in race/focus/qualifying) */}
        {(activePreset === "race" || activePreset === "focus" || activePreset === "qualifying") && (
          <RacePicture />
        )}

        {/* Pit Wall Grid */}
        <div className={`pit-wall preset-${activePreset}`}>
          {activePreset === "race" && <RaceLayout selectedDriver={selectedDriver} />}
          {activePreset === "qualifying" && <QualifyingLayout selectedDriver={selectedDriver} />}
          {activePreset === "telemetry" && <TelemetryLayout selectedDriver={selectedDriver} />}
          {activePreset === "strategy" && <StrategyLayout selectedDriver={selectedDriver} />}
          {activePreset === "focus" && <DriverFocusLayout selectedDriver={selectedDriver} />}
          {activePreset === "minimal" && <MinimalLayout />}
        </div>

        {/* Footer */}
        <footer className="footer">
          DERIVED METRICS ARE ESTIMATED — NOT OFFICIAL FIA DATA
        </footer>
      </div>
    </div>
  );
}

/* ============================================================
   LAYOUT PRESETS
   ============================================================ */

function RaceLayout({ selectedDriver }: { selectedDriver: number | null }) {
  return (
    <>
      <div className="col-timing">
        <TimingTower />
        <WeatherStrip />
      </div>
      <div className="col-main">
        <CircuitMap />
        <TelemetryLab />
        <TyreStrategyTimeline />
      </div>
      <div className="col-intel">
        <BattleRadar />
        <AIConsole />
        <StrategyBoard />
        <SectorIntel />
        {selectedDriver != null && <PaceComparison />}
        <RCFeed />
      </div>
    </>
  );
}

function QualifyingLayout({ selectedDriver }: { selectedDriver: number | null }) {
  return (
    <>
      <div className="col-timing">
        <TimingTower />
        <WeatherStrip />
      </div>
      <div className="col-main">
        <TelemetryLab />
        <SectorIntel />
        {selectedDriver != null && <TheoreticalLap />}
        <TimeDelta />
      </div>
      <div className="col-intel">
        <QualifyingCutLine />
        <AIConsole />
        <RCFeed />
      </div>
    </>
  );
}

function TelemetryLayout({ selectedDriver }: { selectedDriver: number | null }) {
  return (
    <>
      <div className="col-timing">
        <TimingTower />
      </div>
      <div className="col-main">
        <TelemetryLab />
        <SectorIntel />
        {selectedDriver != null && <DegradationDetail driver={selectedDriver} />}
      </div>
      <div className="col-intel">
        <PracticeClassification />
        <BattleRadar />
        <PaceComparison />
        <RCFeed />
      </div>
    </>
  );
}

function StrategyLayout({ selectedDriver }: { selectedDriver: number | null }) {
  return (
    <>
      <div className="col-timing">
        <TimingTower />
        <WeatherStrip />
      </div>
      <div className="col-main">
        <TyreStrategyTimeline />
        {selectedDriver != null && <DegradationDetail driver={selectedDriver} />}
        <CircuitMap />
      </div>
      <div className="col-intel">
        <StrategyBoard />
        <AIConsole />
        <RCFeed />
      </div>
    </>
  );
}

function DriverFocusLayout({ selectedDriver }: { selectedDriver: number | null }) {
  if (!selectedDriver) {
    return (
      <>
        <div className="col-timing">
          <TimingTower />
        </div>
        <div className="col-main" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
          <p className="dim text-lg uppercase" style={{ letterSpacing: "var(--ls-widest)" }}>
            SELECT A DRIVER FROM THE TIMING TOWER
          </p>
        </div>
        <div className="col-intel">
          <RCFeed />
        </div>
      </>
    );
  }

  return (
    <>
      <div className="col-timing">
        <TimingTower />
      </div>
      <div className="col-main">
        <TelemetryLab />
        <LapIntelligence />
        <TimeDelta />
        <TheoreticalLap />
        <SectorIntel />
        <DegradationDetail driver={selectedDriver} />
      </div>
      <div className="col-intel">
        <PaceComparison />
        <PitAnalytics />
        <BattleRadar />
        <StrategyBoard />
        <AIConsole />
        <WhatChanged />
      </div>
    </>
  );
}

function MinimalLayout() {
  return (
    <>
      <div className="col-timing" style={{ maxWidth: 600 }}>
        <TimingTower />
      </div>
    </>
  );
}
