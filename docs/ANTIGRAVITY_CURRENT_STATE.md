# ANTIGRAVITY CURRENT STATE AUDIT

> Generated 2026-08-24. Source of truth: actual source code, tests, docs, git.

---

## 1. Architecture Discovered

```
┌────────────────────────────────────────────────────────────────┐
│  Frontend (React 18 + Vite 5 + TypeScript)                     │
│  Port 5173 → Vite proxy → backend :8000                        │
│  Components: App, TimingTower, TelemetryLab, Panels, AI, Tyres │
│  State: useSyncExternalStore over SessionSocket (snapshot/delta)│
│  WebSocket: f1intel-snapshot-1 protocol (snap → delta → resume)│
└───────────────────────┬────────────────────────────────────────┘
                        │ /ws/session/{id}  +  /api/v1/*
┌───────────────────────▼────────────────────────────────────────┐
│  Backend (FastAPI + asyncpg + Pydantic 2)                      │
│  SessionHub: Provider → IngestPipeline → AnalysisEngine →      │
│              SnapshotDiffer → per-client bounded queues → WS   │
│  250ms publish loop, 400-frame backpressure, eviction policy   │
│  AI: Gateway → Gemini/OpenAI/OpenRouter/Mock → Grounding       │
│  Storage: PostgreSQL/TimescaleDB, LTTB downsampling            │
└────────────────────────────────────────────────────────────────┘
```

### Provider Stack
| Provider | Status | Mode |
|----------|--------|------|
| OpenF1 | **Production** | Live polling + historical backfill |
| F1 SignalR | Implemented, disabled by default | Direct feed abstraction |
| FastF1 | Adapter ready | Historical / high-res analysis |
| Jolpica | Implemented | Schedule / results / standings |
| F1DB | Planned stub | Reference metadata |
| ReplayProvider | **Production** | Session replay from recordings |

### Data Pipeline
`Provider → normalize → validate → dedupe → correct → quality → persist → record`

---

## 2. Backend Discovered

### Core Models (`app/core/models.py` — 10.4KB)
13 canonical entities: SessionInfo, Driver, Lap, SectorTime, PositionUpdate,
TimingInterval, TyreStint, PitStop, WeatherPoint, RaceControlEvent,
TelemetryCarSample, TelemetryLocation, LapCorrection.

### Analysis Engine (`app/analysis/__init__.py` — 26.1KB)
Full deterministic intelligence facade:
- **TimingEngine**: positions, gaps, intervals, personal bests, session bests
- **SectorEngine**: S1/S2/S3 classification (purple/green/yellow), theoretical lap
- **PaceEngine**: rolling-3/5/10, median, pace trend (s/lap slope)
- **StintEngine**: compound tracking, tyre age, degradation fitting (linear reg)
- **GapEngine**: gap-to-leader, interval-to-ahead, clean-air classification
- **BattleDetector**: FSM (APPROACHING → DRS_RANGE → ACTIVE → OVERTAKE → SEPARATING)
- **WeatherEngine**: air/track temp, humidity, wind, rain
- **RaceControlState**: phase (GREEN/YELLOW/SC/VSC/RED_FLAG/CHEQUERED), track flags
- **StrategyEngine2**: pit-loss estimates, 1-stop/2-stop candidates + confidence
- **RacePace2**: driver/team/field-level pace aggregation
- **TrafficModel**: traffic classification per driver
- **DRSAnalyzer**: DRS availability tracking
- **QualifyingIntel**: elimination risk, theoretical gain, cutoff projection, track evolution
- **PracticeIntel**: short run / long run / race sim / qualifying sim classification
- **SignificantEventEngine**: deduplicated event feed with severity levels

### Snapshot Protocol
- `SessionSnapshot` → `SnapshotBuilder.build()` → dict projection
- LeaderboardRow: position, driver_number, lap_number, last_lap_s, personal_best_s,
  gap_to_leader_raw, gap_to_leader_s, interval_s, compound, tyre_age, stint_number,
  rolling5_s, pace_trend_s_per_lap, clean_air, in_pit, retired
- `intelligence()` adds: race_pace_2, tyres_2, traffic, drs, battles_2,
  strategy_candidates, qualifying, practice

### API Endpoints (`app/api/__init__.py` — 24.6KB)
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/v1/health` | GET | Health check |
| `/api/v1/live-data-status` | GET | Provider latency + quality |
| `/api/v1/sessions` | GET | List active sessions |
| `/api/v1/sessions/{id}/snapshot` | GET | Full snapshot dict |
| `/api/v1/sessions/{id}/drivers` | GET | Driver list |
| `/api/v1/sessions/{id}/leaderboard` | GET | Leaderboard rows |
| `/api/v1/sessions/{id}/events` | GET | Event feed |
| `/api/v1/sessions/{id}/sectors/{drv}` | GET | Sector PBs + theoretical |
| `/api/v1/sessions/{id}/tyres/{drv}` | GET | Stint + degradation |
| `/api/v1/sessions/{id}/pace/{drv}` | GET | Rolling pace + trend |
| `/api/v1/sessions/{id}/telemetry/{drv}` | GET | LTTB-downsampled traces |
| `/api/v1/sessions/{id}/telemetry/compare` | GET | Multi-driver comparison |
| `/api/v1/sessions/{id}/intelligence` | GET | Full intelligence pack |
| `/api/v1/sessions/{id}/strategy/candidates` | GET | Strategy candidates |
| `/api/v1/sessions/{id}/contextpack` | GET | AI context pack |
| `/api/v1/sessions/{id}/circuit` | GET | Circuit geometry (returns available=false) |
| `/api/v1/sessions/{id}/ai/ask` | POST | AI question → job |
| `/api/v1/ai/jobs/{id}` | GET | AI job status/result |
| `/api/v1/ai/status` | GET | AI runtime status |
| `/api/v1/replay/{id}/control` | POST | Replay transport controls |
| `/ws/session/{id}` | WS | Realtime snapshot/delta/events/telemetry/ai |

### Realtime (`app/realtime/`)
- **SessionHub**: single upstream → many clients, 250ms batch, backpressure
- **SnapshotDiffer**: delta computation for efficient WS delivery
- **SequenceHistory**: ordered frames, resume support
- **TelemetryCoalescer**: per-driver sample aggregation
- **RealtimeMetrics**: client count, latency, throughput

### AI (`app/ai/`)
- **Gateway**: provider abstraction (Gemini, OpenAI-compatible, OpenRouter, Mock)
- **Jobs**: async job queue with timeout, polling
- **Validation**: grounding validator, evidence IDs, hallucination protection
- **Prompts**: context-aware prompt generation
- **Models**: response schemas with confidence + evidence
- **Change detection**: stale response detection

### Storage (`app/storage/`)
- **PostgreSQL/TimescaleDB**: asyncpg connection pool, migrations
- **LTTB downsampling**: RAW/HIGH/MEDIUM/LOW frequency targets

---

## 3. Frontend Discovered

### Stack
- React 18.3.1, TypeScript 5.5.4, Vite 5.4.0, Vitest 2.0.5
- Zero additional dependencies (no charting library, no state management library)
- Pure SVG telemetry rendering, CSS-only styling

### Component Tree
```
App.tsx
├── TopBar (inline in App.tsx + shell/TopBar.tsx duplicate)
│   ├── StatusBadge (LIVE/REPLAY/CONNECTING/DEGRADED/DISCONNECTED)
│   ├── Session info (country, circuit, session type, lap)
│   ├── Race control banner (RED_FLAG/SAFETY_CAR/VSC)
│   └── Preset bar (RACE CMD / QUALI / TELEMETRY / STRATEGY / DRIVER FOCUS)
├── Dashboard
│   ├── col-timing
│   │   ├── TimingTower (10 columns, memo'd rows, position delta indicators)
│   │   └── WeatherStrip (air, track, humidity, rain)
│   ├── col-main
│   │   ├── TelemetryLab (speed/throttle/brake SVG traces, crosshair cursor)
│   │   └── CircuitFallback (position strip when geometry unavailable)
│   └── col-intel
│       ├── StrategyBoard (candidates table with confidence)
│       ├── BattleRadar (attacker → target, gap, state badge)
│       ├── AIConsole (ask engineer, evidence chips, confidence badge)
│       └── RCFeed (race control event timeline)
└── Footer (DERIVED METRICS disclaimer)
```

### State Management
- `SessionSocket` class in `ws/socket.ts`: WebSocket connection, snapshot/delta protocol
- `useSyncExternalStore` hook via `useSessionState()` — all components share one state
- REST helpers: `apiGet()`, `apiPost()`, `askAI()` (job polling)

### Design System
- `design/tokens.css`: CSS custom properties (surfaces, borders, text, semantic colors, tyre compounds, spacing)
- `styles.css`: component-level styles (separate from tokens — some duplication)
- Stitch reference: `stitch_live_f1_intelligence_console/` with DESIGN.md (Obsidian Telemetry theme) + code.html + screen.png

### Existing Components Summary
| Component | Lines | Completeness |
|-----------|-------|--------------|
| App.tsx | 108 | Functional layout with presets |
| TimingTower.tsx | 115 | 10-col table, memo'd rows, driver selection wired but unused |
| TelemetryLab.tsx | 141 | Speed/throttle/brake SVG, crosshair, REST-fetched |
| Panels.tsx | 168 | Pace, BattleRadar, Weather, RCFeed, Strategy, CircuitFallback |
| AIConsole.tsx | 127 | Ask engineer, evidence, confidence, insight feed |
| TyreTimeline.tsx | 90 | Gantt timeline + degradation detail |
| shared/index.tsx | 107 | Panel, StatusBadge, ConfidenceBadge, TyreChip, TimingValue, EvidenceChip, Metric, Delta |

---

## 4. Existing UX Limitations

1. **No driver selection propagation** — TimingTower has `onSelect` prop but App passes `() => {}`. Selecting a driver does nothing.
2. **No driver comparison** — TelemetryLab accepts `driverB` but it's always `null`.
3. **No session-mode adaptation** — preset buttons exist but all presets render the same layout.
4. **Timing tower missing columns** — spec calls for S1/S2/S3, TEAM, PACE trend; current tower has POS/Δ/DRV/GAP/INT/LAP/LAST/BEST/TYRE/PACE.
5. **No circuit map** — only a fallback position strip.
6. **No tyre strategy timeline in main layout** — component exists but not rendered in App.
7. **No "Race Picture" summary** — leader, closest battle, fastest, pit window.
8. **No live event rail** — events shown only in RCFeed (filtered to RC types).
9. **No data freshness indicators** — no age/staleness display.
10. **No replay controls** — backend supports play/pause/speed but no UI.
11. **No qualifying-specific UI** — Q1/Q2/Q3 phases, cutoff line.
12. **No practice-specific UI** — run classification exists in backend.
13. **No responsive layout** — single-column breakpoint at 1100px, no tablet/mobile optimization.
14. **CSS duplication** — `styles.css` and `tokens.css` both define root variables, some conflicts.
15. **Font loading** — references Inter and JetBrains Mono in stitch design but no `@font-face` or Google Fonts import.
16. **No navigation rail** — stitch design shows left nav rail, current app has none.
17. **Stitch design not integrated** — the `stitch_live_f1_intelligence_console/code.html` is a standalone reference, not connected to the React app. The DESIGN.md specifies detailed typography (Inter/JetBrains Mono), spacing (4px rhythm), elevation, and component specs that aren't fully applied.

---

## 5. Existing Technical Limitations

1. **No intelligence endpoint integration** — frontend doesn't call `/intelligence` to get race_pace_2, tyres_2, traffic, drs, battles_2, strategy_candidates, qualifying, practice.
2. **No sectors API consumption** — theoretical lap and per-driver sectors available but not displayed.
3. **No pace API consumption** — per-driver rolling-3/5/10/median/trend available but only rolling5 shown in leaderboard.
4. **Telemetry refreshes every 500 sequence numbers** — could be smarter.
5. **No sector time display in timing tower** — backend provides S1/S2/S3 via sectors endpoint.
6. **Strategy candidates fetched but only basic table** — no narrative strategy insight.
7. **AI insight feed component exists but not rendered in layout**.
8. **No WebSocket subscription management** — all drivers, all telemetry sent regardless.
9. **Circuit geometry endpoint always returns `available: false`** — no map data source integrated.

---

## 6. Test Coverage

### Backend (21 test files)
- test_ai_layer.py, test_events_engine.py, test_gaps_battles.py, test_gemini_provider.py,
  test_models.py, test_openf1_mapping.py, test_pace.py, test_phase5_intel.py,
  test_phase5_strategy.py, test_pipeline.py, test_provider_compare.py,
  test_provider_contract.py, test_quality.py, test_race_control_session.py,
  test_realtime.py, test_recorder_replay.py, test_replay_gemini_chain.py,
  test_sectors.py, test_timing_engine.py, test_tyres.py
- Real API fixtures in `tests/fixtures/`

### Frontend (2 test files)
- core.test.ts, socket.test.ts

### Scripts
- `live_acceptance.py` (12.5KB) — comprehensive live session validator
- `backtest_analysis.py` — determinism and performance backtesting
- `eval_ai.py` — AI evaluation harness

---

## 7. Recommended Integration Sequence

### Phase A: Foundation (CSS + Design System + Shell)
1. Merge Stitch design tokens into unified `tokens.css`
2. Add Google Fonts (Inter, JetBrains Mono)
3. Build app shell: command header, nav rail, status ribbon
4. Implement responsive grid system
5. Wire driver selection through entire app

### Phase B: P0 Core Pit Wall
1. TimingTower 2.0 — add S1/S2/S3, TEAM, expand columns, compact/expanded modes
2. Race Picture summary bar
3. Circuit map (fallback + future geometry hook)
4. Battle Radar enhancement — gap timeline, closing rate, state badges
5. TelemetryLab 2.0 — gear/RPM/DRS traces, sector boundaries, synchronized cursor
6. Tyre Intelligence 2.0 — integrated timeline, degradation trend, performance comparison
7. Strategy Insight — narrative format, not just table
8. AI Race Engineer — expanded suggestions, structured queries
9. Race Control + Live Event Rail — unified event timeline with filters
10. Weather enhancement — trends, wind direction

### Phase C: P1 Deep Analysis
1. "Where Did The Time Go?" — sector delta visualization
2. Ideal/Theoretical Lap — first-class display
3. Micro-sector visualization (when data available)
4. Pit Stop Intelligence — analytics layer
5. Pit Rejoin Predictor
6. Lap Intelligence — per-lap deterministic summary
7. "What Changed" — last 5 laps narrative
8. Qualifying Cut Line — elimination boundary
9. Practice Run Classification

### Phase D: P2 Advanced Experience
1. Race Story mode
2. Ask The Race (structured AI queries)
3. "What To Watch" suggestions
4. Multiview presets
5. Custom dashboard layouts
6. Broadcast sync utility

### Phase E: Polish + Performance + Testing
1. Data freshness indicators throughout
2. Trust/provenance labels
3. Accessibility pass (keyboard, ARIA, reduced motion)
4. Performance optimization (memoization, virtualization, batched updates)
5. Responsive validation at all target resolutions
6. Visual review loop with screenshots
7. All tests green
