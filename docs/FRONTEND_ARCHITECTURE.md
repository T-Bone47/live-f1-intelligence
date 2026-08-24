# FRONTEND_ARCHITECTURE.md

| | |
|---|---|
| Status | Phase 8 — "Digital Pit Wall" UI/UX |
| Stack | React 18 + TypeScript (strict) + Vite |

---

## Layering (strict)

```
WebSocket + REST          src/ws/socket.ts + src/state/store.ts
       │                  snapshot/delta/resume/seq validation
       ▼
session store             useSessionState() via useSyncExternalStore
       ▼
components/*              render only; dispatch intents only
```

Components NEVER open sockets or fetch directly except via `apiGet`/`apiPost`.
All intelligence (sector classification, degradation estimates, strategy
candidates) comes from the backend — the frontend renders labels.

## Design tokens

`src/design/tokens.css` — CSS custom properties for every color, spacing,
radius, typography, motion, and z-index decision. No random values in
components. Semantic sector colors (purple/green/yellow) are used ONLY for
sector classification, never decoratively.

## Layout presets

| Preset | Emphasis | Panels shown |
|---|---|---|
| RACE CMD | timing + strategy + battles | timing tower, weather, telemetry, circuit, strategy board, battle radar, AI console, RC feed |
| QUALI | sectors + theoretical lap | timing tower, weather, sectors, theoretical, AI console |
| TELEMETRY | speed/throttle/brake traces | full-width telemetry lab |
| STRATEGY | candidates + pit windows + tyres | strategy board + tyre timeline |
| DRIVER FOCUS | selected driver detail | driver drawer + telemetry |

## Component structure

```
components/
├── shell/TopBar.tsx           status badge, session info, presets
├── shared/index.tsx           Panel, TyreChip, ConfidenceBadge, EvidenceChip,
│                              Metric, Delta
├── timing/TimingTower.tsx     broadcast-quality timing table
├── telemetry/TelemetryLab.tsx synchronized speed/throttle/brake traces
├── panels/Panels.tsx          PacePanel, BattleRadar, WeatherStrip,
│                              RCFeed, StrategyBoard, CircuitFallback
├── ai/AIConsole.tsx           grounded AI answers + insight feed
├── tyres/TyreTimeline.tsx     Gantt-style stint timeline
└── App.tsx                    layout presets + session-mode emphasis
```
