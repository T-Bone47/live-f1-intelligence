# PROJECT_SPEC.md — LIVE F1 INTELLIGENCE

| | |
|---|---|
| Status | Phase 0 — Approved draft, awaiting sign-off |
| Date | 2026-08-23 |
| Phase | 0 (Architecture & Research) |
| Implementation | NOT STARTED (per Phase 0 rules) |

---

## 1. What this is

A **production-quality real-time Formula 1 intelligence platform** that:

1. Ingests legitimate F1 session data (live and historical).
2. Normalizes it into canonical schemas independent of any provider.
3. Computes derived intelligence deterministically (pace, degradation, battles,
   strategy windows, theoretical laps).
4. Detects meaningful events from the data stream.
5. Uses LLMs **only** on pre-computed context packs to explain events and answer
   questions — never as a real-time telemetry processor.
6. Replays recorded sessions through the exact same pipeline as live sessions.

It is a professional motorsport analytics product, not a game, not a stats
website, and not a bare timing screen.

## 2. What this is NOT

- Not an F1 management/fantasy game.
- Not a static statistics site.
- Not merely a live-timing clone.
- Not an official F1 product. All data is from unofficial/community sources.
  See `DATA_SOURCES.md §9` for legal posture.
- Not a system that fabricates data: missing data stays missing; every number
  shown is labeled by provenance class (see §5).

## 3. Session coverage

All session types share one pipeline; only mode profiles differ:

| Session type | Mode profile | Distinct analysis focus |
|---|---|---|
| FP1/FP2/FP3 | `PRACTICE` | Run segmentation (short/long), race & quali sims, tyre comparison, track evolution |
| Sprint Qualifying / Shootout | `QUALIFYING` | Parts (SQ1–SQ3), elimination risk, projected cutoff |
| Sprint | `SPRINT` | Short-race pace, tyre strategy, battles |
| Qualifying | `QUALIFYING` | Q1/Q2/Q3, theoretical lap, track evolution, traffic |
| Race | `RACE` | Pace, degradation, strategy, pits, SC/VSC, projection |
| Post-session | `POST` | Full-session analytics over stored canonical data |
| Historical replay | `REPLAY` (any of the above + clock control) | Same analyzers, virtual clock |

Details: `SESSION_MODES.md`.

## 4. Feature catalog

Each feature is tagged with the highest provenance class required:

- **A** Direct live data (observed, received in real time)
- **B** Historical data (observed, received after the fact)
- **C** Derived data (deterministic calculation from A/B)
- **D** Statistical/model prediction
- **E** LLM interpretation
- **F** Unavailable (documented so nobody fakes it)

### 4.1 Live timing
Leaderboard: position, driver, team, lap, lap time, gap, interval, best/last
lap, pit status, position changes, driver status. `[A/B]`
Gaps/intervals come from the timing feed; we recompute where feeds disagree.

### 4.2 Sector intelligence
Live sector times, purple/green/yellow classification, personal-best and
session-best sectors, sector deltas driver-vs-driver, sector trend lines,
theoretical best lap (sum of each driver's best sectors). `[A + C]`

### 4.3 Live telemetry
Speed, throttle, brake, gear, RPM, DRS at ~3.5 Hz per car; coarse GPS
(x/y/z ~3.7 Hz); distance-around-lap computed from GPS vs. track map. `[A/B]`
Driver-vs-driver comparison, lap overlays, speed traces, corner analysis where
data resolution permits. `[C]`
**F-class honesty**: no lateral track placement beyond coarse coordinates, no
tyre temps, no suspension/steering/fuel/ERS channels, no sub-3.5 Hz ECU data.

### 4.4 Tyre intelligence
Compound, age, stint length, stint pace, pace-vs-age curves, degradation
estimate/trend (regression over clean-lap samples), warm-up behavior, expected
remaining life `[C/D]`, compound comparison `[C]`.

### 4.5 Race pace
Rolling 3/5/10-lap pace, stint average, outlier-filtered pace (robust
statistics), clean-air pace, traffic-adjusted pace `[C]`, tyre-adjusted pace
`[D]`, pace trend `[C]`.
The platform always distinguishes *fastest lap* from *competitive pace*.

### 4.6 Strategy
Pit windows, undercut/overcut threat detection, pit-loss estimation (from
observed pit lane times + GPS), alternative scenarios (1-stop/2-stop),
SC/VSC variants, race projection `[C/D]`.

### 4.7 Battle intelligence
Battle detection (gap threshold + sustained proximity), gap evolution, closing
rate, DRS-range detection (gap ≤ 1s at detection point), tyre delta, sector
advantage attribution. `[A + C]`

### 4.8 Weather / track
Air temp, track temp, humidity, wind speed/direction, rain flag (~60 s cadence)
`[A/B]`; track-evolution index (session-fastest-lap trend), temperature and
weather trends, strategy implications `[C/D]`.

### 4.9 Race control
Green/yellow/double-yellow, SC, VSC, red flag, track limits, deleted lap
times, penalties, investigations — mapped from RaceControlMessages `[A/B]`.

### 4.10 Session-specific intelligence
See `SESSION_MODES.md`. Practice run classification `[C]`, quali elimination
projection `[C/D]`, sprint/race strategy engines `[C/D]`.

### 4.11 AI race engineer
Event explanations, grounded Q&A ("why is Norris faster?", "should Ferrari
pit?"), change summaries ("what changed in the last five laps?"), narrative
post-session reports. Every AI output labels observed data, calculated metrics,
predictions, and interpretation separately. `[E over A/C/D context packs]`

### 4.12 Replay
Any recorded session replayable as-if-live with variable speed, seek, and the
full event/insight timeline. `REPLAY_ARCHITECTURE.md`.

## 5. Provenance classes (platform-wide rule)

Every persisted value and every UI element carries exactly one class:

| Class | Meaning | Example |
|---|---|---|
| A | Direct live observation | Sector time just received |
| B | Historical observation | 2024 Monaco pole lap |
| C | Deterministic derivation | Rolling 5-lap pace |
| D | Model prediction | "Tyre life remaining ≈ 6 laps" |
| E | LLM interpretation | Narrative explanation |
| F | Unavailable | Front-left tyre temperature |

Rule: **class F is never rendered as if it exists.** Class E content is always
visually distinct from A/C/D.

## 6. MVP definition

The MVP is the smallest system that proves the full thesis end-to-end:
*live data → normalization → deterministic intelligence → event detection →
grounded AI → delivery.*

Included:
1. One ingestion provider live (`signalrcore` direct feed) + one fallback
   (OpenF1 REST/MQTT) behind the provider abstraction.
2. Canonical normalization + raw recording (replay-capable from day one).
3. Leaderboard, sectors, tyres/stints, basic rolling pace, race control,
   weather.
4. Event engine v1 (purple sectors, personal bests, position changes, flag
   changes, pit stops, battle start/end).
5. AI engineer: event explanations + chat grounded in context packs.
6. WebSocket gateway + minimal functional readout client (not the final
   frontend product).
7. Replay playback of anything recorded.

Explicitly postponed: full frontend product, ClickHouse/TimescaleDB, ML
degradation models beyond regression, team-radio transcription, multi-user
accounts, notifications, mini-sectors, Kubernetes. Rationale per item in
`DECISIONS.md`.

## 7. Success criteria

- End-to-end latency (source event → client message): **≤ 3 s p95** for live
  sessions via direct feed (bounded by source, measured, not assumed).
- Zero fabricated values anywhere in the stack; provenance label on every
  displayed metric.
- Replay of a recorded session produces identical analyzer output to the live
  run for the same input frames (parity test).
- Provider switch test: swapping OpenF1 ↔ direct feed requires configuration
  only, no core code changes.
- AI answers cite only values present in the supplied context pack; automated
  grounding check rejects unsupported claims.

## 8. Constraints & ground rules (from project charter)

1. No fake telemetry, ever. Missing = absent.
2. No continuous raw telemetry to LLMs.
3. Provider abstraction mandatory; no hard-coded vendor schemas outside the
   provider layer.
4. No unnecessary microservices; single deployable backend for MVP.
5. Secrets only via environment/config; nothing committed.
6. Real-time claims must match verified source latency.
7. Non-commercial posture until licensing is resolved (`DATA_SOURCES.md §9`).

## 9. Repository layout

Proposed structure (created in Phase 1):

```
live-f1-intelligence/
├── docs/                     # Phase 0 documents (this set)
├── backend/
│   ├── app/
│   │   ├── providers/        # openf1/, livetiming/, jolpica/, base.py
│   │   ├── ingest/           # signalr client, pollers, recorders
│   │   ├── normalize/        # provider -> canonical transforms
│   │   ├── core/             # canonical models, session state, clock
│   │   ├── analysis/         # pace, tyres, sectors, battles, strategy
│   │   ├── events/           # envelope, bus, detectors
│   │   ├── ai/               # context builder, llm adapters, guardrails
│   │   ├── storage/          # postgres, redis, recording store
│   │   ├── api/              # FastAPI routers, WS gateway
│   │   └── config.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/                 # Phase 6+ (empty placeholder)
├── ops/                      # docker-compose, env templates
├── tools/                    # recorder CLI, replayer CLI, fixtures
└── README.md
```

Full rationale: `DECISIONS.md §12`.

## 10. Related documents

`ARCHITECTURE.md` · `DATA_SOURCES.md` · `DATA_MODEL.md` · `EVENT_SCHEMA.md` ·
`AI_ARCHITECTURE.md` · `SESSION_MODES.md` · `REPLAY_ARCHITECTURE.md` ·
`API_CONTRACT.md` · `IMPLEMENTATION_ROADMAP.md` · `TECHNICAL_RISKS.md` ·
`DECISIONS.md`
