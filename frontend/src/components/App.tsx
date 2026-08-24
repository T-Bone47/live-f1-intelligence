/** Digital Pit Wall — layout presets + session-mode awareness.
 *  Frontend = presentation only. All intelligence from backend. */

import { useState } from "react";
import { useSessionState } from "../state/store";
import { StatusBadge, Panel } from "./shared/index";
import { TimingTower } from "./timing/TimingTower";
import { TelemetryLab } from "./telemetry/TelemetryLab";
import {
  BattleRadar, WeatherStrip, RCFeed,
  StrategyBoard, CircuitFallback,
} from "./panels/Panels";
import { AIConsole } from "./ai/AIConsole";

type Preset = "RACE" | "QUALIFYING" | "TELEMETRY" | "STRATEGY" | "FOCUS";

const PRESETS: { key: Preset; label: string }[] = [
  { key: "RACE", label: "RACE CMD" },
  { key: "QUALIFYING", label: "QUALI" },
  { key: "TELEMETRY", label: "TELEMETRY" },
  { key: "STRATEGY", label: "STRATEGY" },
  { key: "FOCUS", label: "DRIVER FOCUS" },
];

function TopBar({ preset, onPreset }: { preset: Preset; onPreset: (p: Preset) => void }) {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const mode = st.status;
  const sessionType = snap?.session_type ?? snap?.profile ?? "";
  const circuit = snap?.circuit_short_name ?? "";
  const lap = snap?.current_lap ? `LAP ${snap.current_lap}` : "";
  const phase = snap?.phase ?? "";

  return (
    <header className="topbar" role="banner">
      <div className="topbar-row">
        <StatusBadge status={mode} />
        <div className="title-block">
          <strong>F1 INTELLIGENCE</strong>
          <span className="session-info dim">
            {[snap?.country_code, circuit, String(sessionType), lap].filter(Boolean).join(" \u00B7 ")}
          </span>
        </div>
        {["RED_FLAG", "SAFETY_CAR", "VSC"].includes(phase) && (
          <span className={`rc-banner rc-${phase.toLowerCase()}`} role="alert">
            {phase.replace(/_/g, " ")}
          </span>
        )}
        <div className="topbar-right mono dim text-xs">
          <span>seq {st.seq}</span>
        </div>
      </div>
      <nav className="preset-bar" role="toolbar" aria-label="Layout presets">
        {PRESETS.map(p => (
          <button key={p.key} type="button"
                  className={`preset-btn ${preset === p.key ? "active" : ""}`}
                  onClick={() => onPreset(p.key)}
                  aria-pressed={preset === p.key}>{p.label}</button>
        ))}
      </nav>
    </header>
  );
}

export function Dashboard({ preset }: { preset: Preset }) {
  const st = useSessionState();
  const [selectedDriver, setSelectedDriver] = useState<number | null>(null);
  const snap = st.snapshot as any;
  const profile = (snap?.profile ?? snap?.session_type ?? "").toString().toUpperCase();
  const isRaceLike = profile.includes("RACE") || profile.includes("SPRINT");

  return (
    <main className={`pit-wall preset-${preset.toLowerCase()}`}>
      <section className="col-timing">
        <Panel title="TIMING TOWER"><TimingTower /></Panel>
        <WeatherStrip />
      </section>
      <section className="col-main">
        <TelemetryLab driverA={selectedDriver} driverB={null} />
        <CircuitFallback />
      </section>
      <aside className="col-intel">
        {(isRaceLike || preset === "STRATEGY") && (
          <>
            <StrategyBoard />
            <BattleRadar />
          </>
        )}
        <AIConsole />
        <RCFeed />
      </aside>
    </main>
  );
}

export function App() {
  const [preset, setPreset] = useState<Preset>("RACE");
  return (
    <div className="app">
      <TopBar preset={preset} onPreset={setPreset} />
      <Dashboard preset={preset} />
      <footer className="footer mono dim text-xs">
        DERIVED METRICS \u00B7 NOT OFFICIAL F1 DATA
      </footer>
    </div>
  );
}
