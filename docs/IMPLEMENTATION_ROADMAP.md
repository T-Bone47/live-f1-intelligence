# IMPLEMENTATION_ROADMAP.md

| | |
|---|---|
| Status | Phase 0 — awaiting approval to begin Phase 1 |
| Rule | Each phase ends with runnable, tested software. No phase starts without the previous one merged. |

---

## Phase 1 — Foundation (≈1 week)

**Goal**: skeleton that runs and is wired for CI.

- Repo scaffolding per DECISIONS.md §12 layout; Python 3.12 + uv/pip-tools
  pinning; ruff + mypy strict; pytest; GitHub Actions (lint/type/test).
- Canonical models package (`core/models`) from DATA_MODEL.md (pydantic v2).
- Config system (pydantic-settings), structured logging, secrets via env.
- `ops/docker-compose.yml`: postgres + redis (+ backend dev service).
- ADR habit begins: DECISIONS.md updated with every choice.
- **Exit criteria**: CI green on empty-pipeline smoke test; compose up works.

## Phase 2 — Ingestion & recording (≈2 weeks)

**Goal**: data flows in and lands on disk, replayable byte-for-byte.

- `LiveTimingProvider` (signalrcore): negotiate/handshake/subscribe, snapshot +
  feed handling, ping tolerance, supervisor w/ reconnect+resync. Optional
  bearer-token auth path behind config.
- Raw archive writer (.jsonl.zst) + canonical frame recorder (ReplayFrame).
- Normalizer v1: DriverList, SessionInfo/Status, TimingData → laps/sectors,
  TimingAppData → stints/pits, RCM, TrackStatus, LapCount, WeatherData.
  CarData.z/Position.z decode → TelemetryPoint.
- `tools/replay_cli.py` — fold a recording to final state hash (parity tool).
- Fixture corpus: record whatever sessions occur during this phase (any type).
- **Exit criteria**: recorded session replays to identical state hash twice;
  laps/sectors/stints cross-checked against FastF1 output for one historical
  session within tolerance (documented diffs).

## Phase 3 — State & analysis core (≈2–3 weeks)

**Goal**: deterministic intelligence over canonical stream.

- SessionState fold/snapshot engine; Redis snapshot publisher.
- Analyzers: SectorAnalyzer (purple/PB/theoretical), PaceAnalyzer
  (rolling windows, outlier filtering, clean-air flag), TyreAnalyzer (stints,
  degradation slope, warm-up), WeatherTrackAnalyzer (evolution index),
  BattleAnalyzer (gap series, closing rate, DRS-range).
- Event engine: envelope bus, dedupe, hysteresis config, priorities.
- Persistence: PG schema migration (alembic) + batch writers; query layer.
- Unit tests with synthetic frames + golden fixtures from Phase 2 recordings.
- **Exit criteria**: full-session batch analysis of a fixture produces stable,
  reviewed metric outputs (pace tables, degradation slopes vs. hand checks).

## Phase 4 — Live gateway & strategy v1 (≈2 weeks)

**Goal**: observable live platform without the product frontend.

- FastAPI REST per API_CONTRACT.md subset + WS gateway (snapshot/batch/resume)
  + SSE fallback; OpenAPI published.
- StrategyAnalyzer v1: pit-loss estimation from observed lane times, pit
  windows, undercut/overcut threat events; SC/VSC status integration.
- Minimal operational console (single-page, read-only, generated from WS —
  explicitly NOT the product UI; may be CLI/table view if faster).
- Provider fallback wiring: direct feed primary; OpenF1 live (paid) secondary;
  capability descriptor plumbing end-to-end.
- Load test: simulated 20× viewer fan-out against recorded session.
- **Exit criteria**: end-to-end latency measured ≤3 s p95 on fixtures + one
  real live session observed; resume-after-gap verified under kill -9 chaos.

## Phase 5 — AI engineer (≈2 weeks)

**Goal**: grounded explanations and chat.

- Context-pack builder + template registry (versioned YAML); LLM adapter
  (OpenAI-compatible) + budgets/cooldowns/caching.
- Grounding validator + claims schema; AIEvent persistence incl. packs.
- Chat endpoint + WS delivery; digest job; evaluation harness with labeled
  golden set (≥50 events across ≥3 sessions).
- **Exit criteria**: grounding-pass-rate ≥95% on eval set; zero unsupported
  numeric claims escaping validator in adversarial tests.

## Phase 6 — Product frontend (≈3–4 weeks)

**Goal**: professional motorsport analytics UI (first release).

- Next.js + TS app consuming API contract types (codegen); design system:
  dense, dark, information-first; no fake metrics ever rendered.
- Views: Live dashboard (leaderboard, gaps, tyres, sector strip, race control
  ticker, weather strip), driver detail (lap chart, tyre/pace trends,
  telemetry overlays), battles panel, strategy panel, AI engineer drawer,
  replay theater (seek/speed/event timeline), post-session reports.
- Track map from Position.z-derived centerline (Phase 6 stretch; else omit —
  never fake).
- **Exit criteria**: usability pass on a live race weekend; parity between WS
  latency and perceived updates ≤4 s p95.

## Phase 7 — Hardening & scale (≈2 weeks)

- Multi-session concurrency (per-session worker leases via Redis), monthly
  partitions, backup/restore drill, metrics (Prometheus), alerting, runbook.
- Optional: TimescaleDB evaluation for telemetry; mini-sectors from own track
  maps; team-radio STT experiment (clearly class-C/D derived transcript).

## Post-MVP backlog (not scheduled)

Championship-impact projections, multi-season comparative analytics,
ClickHouse warehouse, mobile apps, public sharing pages, notifications
(webhook/mobile push), ML upgrade path (gradient-boosted degradation, learned
SC predictor), i18n.

## Dependency graph

```
P1 ─ P2 ─ P3 ─ P4 ─ P6 ─ P7
          └── P5 ──┘(chat UI lands in P6)
```

## Estimation honesty

Estimates assume one senior engineer full-time plus review capacity; they are
planning anchors, not commitments. Recording (P2) must start ASAP regardless —
every missed session is lost replay/AI-eval corpus.
