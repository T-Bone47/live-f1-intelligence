# LIVE F1 INTELLIGENCE

A production-grade real-time Formula 1 intelligence platform.

**Status: Phase 2 — deterministic intelligence engine (working, backtested).**

- Phase 1: ingestion foundation — **1,067,193 canonical events** from the real
  2026 Dutch GP with 0 malformed records; full DB rebuild from recording alone.
- Phase 1.5: multi-provider strategy (OpenF1 / SignalR / FastF1 / Jolpica /
  F1DB / Replay), session-state projection, lap tombstones.
- Phase 2: `app/analysis/` deterministic engines — timing, sectors
  (purple/green/yellow + theoretical), lap classification, rolling pace +
  clean-air, ESTIMATED tyre degradation, gaps/battles FSM, strategy
  primitives, weather trends, significant-event detection with dedupe,
  SessionSnapshot. Backtested against the real race recording:
  **determinism PASS**, ~2,650 events/s, p50 0.10 ms/event, 99 MB peak.

Phase 1 proved the foundation on real data: **1,067,193 canonical events**
ingested from the 2026 Dutch GP with 0 malformed records, and a full database
rebuild from the recording alone via the replay path.

Phase 1.5 added the complete provider strategy:

| Provider | Role | Status |
|---|---|---|
| OpenF1 | primary live/fallback + historical | production |
| F1 SignalR Core | direct feed abstraction (verified token-less negotiate/snapshot 2026-08-24) | implemented, disabled by default |
| FastF1 | historical/high-res analysis (class B only) | adapter ready |
| Jolpica | schedule/results/standings | implemented |
| F1DB | reference metadata | planned stub |
| Replay | provider-independent recordings | production |

Plus: session-state projection, lap tombstone/correction ledger (verified on
real race-control data), source-priority matrix, never-merge reconciliation
policy, provider-level quality metrics, failover chain runner.

---

## What works today

| Capability | Status |
|---|---|
| Provider abstraction w/ honest capability descriptors | done |
| OpenF1 provider (historical backfill + live polling modes) | done |
| Canonical schemas (13 entities) + provenance classes A–F | done |
| Event envelope + deterministic in-process bus | done |
| Validation / dedupe / malformed-isolation | done |
| PostgreSQL persistence (migrations; TimescaleDB optional) | done |
| Session recording (.jsonl.zst) + ReplayProvider stub | done |
| Data-quality monitor incl. latency percentiles | done |
| CLI tools (discover/record/inspect/data_quality/replay) | done |
| 50 unit tests on real-API fixtures | passing |

Not yet (by design): direct F1 feed, analysis engines, AI, product frontend —
see `docs/IMPLEMENTATION_ROADMAP.md`.

## Repository layout

```
backend/
  app/
    providers/        base.py + openf1/ + replay.py   (vendor edge only)
    ingest/           pipeline, normalize, recorder, quality, persistence
    core/             canonical models, enums, event envelope/bus
    storage/          asyncpg pool, migrations/, repository
  tests/              fixtures = real captured API responses
scripts/              discover_sessions, record_session, inspect_session,
                      data_quality, replay_session, probe_*
ops/                  docker-compose.yml (Timescale), .env.example
docs/                 Phase-0 architecture set + Phase-1 guides
recordings/           session recordings (gitignored)
```

## Setup (Windows PowerShell)

```powershell
# 1. Python deps
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. Database — either Docker (needs Docker Desktop running):
docker compose -f ..\ops\docker-compose.yml up -d
# ...or a local PostgreSQL; point DATABASE_URL at it.
# NOTE verified on this machine: Hyper-V/WSL2 unavailable -> docker compose
# will not start until virtualization is enabled; a local/native Postgres
# works fine (that is how acceptance was run).

# 3. Configuration
Create a local `.env` (gitignored — never commit real keys). Required for AI:

    GEMINI_API_KEY=your_key_here

All other variables are optional with sensible defaults — see the
**Configuration** section below.
```

## Usage

```powershell
# list sessions
python scripts\discover_sessions.py --latest

# record a full session (backfill or live); prints CONNECTING ->
# SESSION FOUND -> RECEIVING DATA -> RECORDING -> STOPPED + quality report
python scripts\record_session.py --ref openf1:11353 --max-seconds 1500

# inspect what landed in Postgres
python scripts\inspect_session.py openf1:11353

# data-quality report
python scripts\data_quality.py openf1:11353

# prove replay: rebuild DB state FROM the recording via the same pipeline
python scripts\replay_session.py recordings\openf1-11353-race --speed 0 --persist

# run the test suite
cd backend ; .venv\Scripts\python.exe -m pytest tests -q
```

## Configuration

Create .env in the project root (already gitignored). Only the Gemini key is
required for AI features; everything else defaults sensibly:

| Variable | Default | Purpose |
|---|---|---|
| GEMINI_API_KEY | — | Google Gemini Developer API key (AI race engineer). **Server-side only.** |
| LLM_PROVIDER | mock | mock \| gemini \| openai-compatible |
| LLM_MODEL | mock-grounded-1 | model id, e.g. gemini-2.5-flash |
| LLM_BASE_URL | https://api.openai.com/v1 | any OpenAI-compatible endpoint incl. OpenRouter |
| LLM_API_KEY | — | key for openai-compatible providers |
| LLM_AUTO_COMMENTARY | true | automatic event commentary on/off |
| DATABASE_URL | postgresql://f1intel:f1intel_dev@localhost:5433/f1intel | Postgres/Timescale DSN |
| OPENF1_RATE_LIMIT_RPS / _RPM | 1.8 / 20 | client-side OpenF1 throttle |
| OPENF1_API_TOKEN | — | OpenF1 sponsor token (live window) |
| SIGNALR_ENABLED / F1_BEARER_TOKEN | false / — | direct F1 feed (Phase 6.1 note) |
| POLL_INTERVAL_SECONDS / RECORDINGS_DIR | 6.0 / recordings | ingest tuning |

ops/.env.example intentionally contains only GEMINI_API_KEY= per project
policy; this table is the authoritative variable reference.

## Documentation

- `docs/DATA_PIPELINE.md` — flow, channels, dedupe keys, recording format
- `docs/PROVIDER_GUIDE.md` — provider contract + VERIFIED OpenF1 behavior
- `docs/DATA_QUALITY.md` — metrics, interpretation, latency policy
- `docs/DATA_SOURCES.md` — source research + empirical findings (§11)
- `docs/*.md` — Phase-0 architecture set (spec, model, AI, roadmap…)

## Ground rules honored

No fabricated data anywhere: missing values stay NULL, unknown enums map to
`*_UNKNOWN`, lapped-car gaps are preserved verbatim (`gap_raw='+1 LAP'`),
latency claims require measurement. Secrets only via `.env`.
