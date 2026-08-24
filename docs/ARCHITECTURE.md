# ARCHITECTURE.md

| | |
|---|---|
| Status | Phase 0 |
| Scope | System design for LIVE F1 INTELLIGENCE |

---

## 1. Guiding principles

1. **One pipeline, two clocks.** Live and replay feed the identical processing
   chain; only the clock source differs.
2. **Providers are plugins.** Nothing above the `providers/` layer knows a
   vendor schema. Canonical models are the only interchange format.
3. **Determinism before intelligence.** Everything computable is computed
   deterministically; LLMs only ever see precomputed, bounded context packs.
4. **Missing data is a state, not an error.** Capability descriptors and
   provenance classes propagate end-to-end.
5. **Boring scale-out story.** A single deployable backend handles a race
   weekend; horizontal scaling is achieved by stateless gateways + Redis
   pub/sub, not by microservice sprawl.

## 2. Topology

```
                        ┌──────────────────────────────┐
  F1 signalrcore ──────▶│  INGESTION (provider adapter)│──── raw archive (.jsonl.zst)
  OpenF1 REST/MQTT ────▶│  - connect/poll supervision  │
  Jolpica (nightly) ───▶│  - reconnect/backoff         │
                        └──────────┬───────────────────┘
                                   │ provider frames
                        ┌──────────▼───────────┐
                        │ NORMALIZER           │ vendor schema → canonical models
                        │ validation, units,   │
                        │ tombstones, dedupe   │
                        └──────────┬───────────┘
                                   │ canonical events (async queue)
                 ┌─────────────────┼──────────────────────┐
                 ▼                 ▼                      ▼
        ┌────────────────┐ ┌──────────────────┐ ┌──────────────────┐
        │ SESSION STATE  │ │ ANALYSIS ENGINE  │ │ RECORDER         │
        │ authoritative  │ │ pace/tyre/battle │ │ canonical frames │
        │ in-memory      │ │ strategy/sector  │ │ → storage        │
        └───────┬────────┘ └────────┬─────────┘ └──────────────────┘
                │                   │ detected events
                │            ┌──────▼───────┐
                │            │ EVENT ENGINE │ thresholds, windows,
                │            │              │ dedupe, priorities
                │            └──────┬───────┘
                ▼                   ▼
        ┌─────────────────────────────────────┐     ┌───────────────┐
        │ PERSISTENCE                         │     │ AI ENGINE     │
        │ Postgres (canonical)               │◀────│ context pack  │
        │ Redis (live snapshot, pub/sub)     │     │ builder → LLM │
        └───────────────┬─────────────────────┘     └───────┬───────┘
                        │ subscribe                          │ insights
                ┌───────▼────────────┐                              │
                │ API GATEWAY        │◀─────────────────────────────┘
                │ FastAPI REST + WS  │
                └───────┬────────────┘
                        │ ws://… / rest …
                  FRONTEND CLIENTS (Phase 6+), tools, notebooks
```

## 3. Component specifications

### 3.1 Ingestion service (`ingest/` + `providers/`)
- One supervisor task per active source with exponential backoff, jittered
  reconnects, heartbeat watchdogs (feed silent > N s ⇒ forced resync).
- `LiveTimingProvider`: SignalR Core client — OPTIONS pre-flight (AWSALBCORS
  cookie) → POST negotiate → WSS handshake (`{"protocol":"json","version":1}` +
  `\x1e`) → Subscribe(topics) → consume type-3 completion as initial snapshot,
  then type-1 `feed` invocations; skip pings/others. Optional bearer-token auth
  path (config-driven) because upstream auth posture is unstable.
- `OpenF1Provider`: MQTT/WS subscription when sponsored-live; REST poller with
  token-bucket (≤ limits) otherwise; historical backfill via paginated queries.
- `JolpicaProvider`: scheduled sync (schedule/results/standings/metadata).
- Raw archive: every provider frame appended to session-scoped `.jsonl.zst`
  with wall-clock receipt timestamp — this is the replay source of truth and
  the debugging black box.

### 3.2 Normalizer (`normalize/`)
Pure functions: vendor frame → canonical events/models. Responsibilities:
unit normalization, UTC timestamps, driver-number ↔ driver-id resolution,
deflate decompression of `.z` topics, lap/sector assembly from splits,
tombstoning deleted laps, idempotent upserts, conflict flags when feed values
disagree with recomputation.

### 3.3 Session state (`core/state.py`)
In-memory authoritative projection per active session: leaderboard, current
lap, sectors, stints, gaps, flags, weather, pits. Rebuildable at any time by
folding recorded frames (this *is* replay). Snapshot published to Redis on
change (throttled to ≤ 5 Hz) for gateway fan-out.

### 3.4 Analysis engine (`analysis/`)
Stateful analyzers consuming canonical events, each owning its own incremental
state and emitting analytical events:

| Analyzer | Emits |
|---|---|
| SectorAnalyzer | purple/green/yellow sector, PB/SB updates, theoretical lap changes |
| PaceAnalyzer | rolling 3/5/10 pace, stint pace, outlier-filtered pace, clean-air flag, pace trend |
| TyreAnalyzer | stint records, degradation slope, warm-up profile, projected life |
| StrategyAnalyzer | pit windows, undercut/overcut threats, pit-loss estimates, scenario table |
| BattleAnalyzer | battle start/end, closing rate, DRS-range, tyre deltas |
| WeatherTrackAnalyzer | evolution index, temp trends, condition-change alerts |
| QualiAnalyzer (mode) | part progress, elimination risk, projected cutoff |
| PracticeAnalyzer (mode) | run segmentation (push/cool/long-run), sim classification |

All numeric work in numpy/pandas over small rolling buffers; hot path avoids
DataFrame churn (plain dataclasses + numpy arrays per window).

### 3.5 Event engine (`events/`)
Canonical envelope (see EVENT_SCHEMA.md): detection rules = pure predicates
over analyzer outputs with hysteresis/debounce so flapping doesn't spam;
priority levels drive UI surfacing and AI urgency; every event carries
provenance class.

### 3.6 Persistence
- **PostgreSQL**: sessions, drivers, teams, laps, sectors, stints, pits,
  weather, RCM, strategy/battle/AI events, insight records. Batched COPY-style
  inserts (~150 telemetry rows/s peak is trivial). TimescaleDB optional later
  for telemetry hypertables — schema stays plain-SQL compatible meanwhile.
- **Redis**: live session snapshots (hash + JSON), event stream (Streams),
  WS fan-out pub/sub, LLM response cache, rate-limit tokens.
- **Object/local store**: raw archives + normalized frame recordings
  (`.jsonl.zst`), indexed in PG (session, byte ranges, frame counts).

Deliberately excluded for MVP: Kafka/NATS (asyncio queues internally; Redis
Streams at the boundary), ClickHouse (volume doesn't justify it).

### 3.7 AI engine (`ai/`)
Context-pack builder (deterministic selectors over state/analytics) →
provider-agnostic LLM adapter → structured-output validation → grounding
check (every claim must reference pack element ids) → publish as AIEvent.
Hard budget: N calls/min, M tokens/session-hour, per-user chat caps. Full spec:
AI_ARCHITECTURE.md.

### 3.8 API gateway (`api/`)
FastAPI: REST for resources/replay control, WebSocket for live streams with
topic subscriptions, SSE fallback. Stateless; reads snapshots from Redis so N
gateways can scale behind a load balancer. Contract: API_CONTRACT.md.

### 3.9 Clock service (`core/clock.py`)
Single monotonic session-time authority per running session. Live mode =
wall-clock anchored by Heartbeat/ExtrapolatedClock; Replay mode = virtual
clock (variable speed, seek, pause). All analyzers key off session time.

## 4. Live ⇄ replay parity

`ReplayProvider` implements `ProviderPort` exactly like live providers: it
reads a normalized recording and emits frames stamped with their original
session timestamps against the virtual clock. Downstream (normalizer→analysis
→events→storage→gateway) cannot tell live from replay except via a mode flag.
Parity test: fold recording X live-recorded vs replay X ⇒ identical final
session state hash. See REPLAY_ARCHITECTURE.md.

## 5. Technology choices & rationale

| Layer | Choice | Why | Alternatives rejected |
|---|---|---|---|
| Language (backend) | Python 3.12 | ecosystem fit (FastF1/OpenF1 tooling, pandas/numpy analytics), async I/O adequate at our volumes (<200 msg/s) | Rust (perf unneeded, slower iteration), Node (weaker numerics) |
| API framework | FastAPI + uvicorn[uvloop] | native async, WS support, pydantic v2 shared schemas, OpenAPI for free | Django (ORM-centric), Flask (no async-first) |
| Streaming internals | asyncio queues | zero infra, single-process MVP | Kafka/NATS (ops cost ≫ need at <200 msg/s) |
| Cross-process bus/cache | Redis 7 (Streams, Pub/Sub, keys) | snapshot fan-out, gateway scale-out, TTL caches | Memcached (no persistence/pubsub), NATS (another server to run) |
| OLTP store | PostgreSQL 16 | relational integrity for canonical entities, JSONB where flexible | Mongo (schemaless invites drift), SQLite (dev-only fallback supported) |
| Time-series | plain tables now; TimescaleDB optional Phase 4+ | telemetry volume tiny (~150 rows/s peak); avoid premature ops burden | ClickHouse (revisit if multi-season analytics productized) |
| Recording format | zstd-compressed JSONL | append-only, streamable, greppable, language-neutral | Parquet for raw frames (write-amplification on appends), custom binary (opaque) |
| Frontend | Next.js + TS (Phase 6+) | product-grade UI stack, SSR marketing pages + CSR dashboard | SvelteKit (fine but smaller hiring pool) |
| Deployment | docker compose (single host) | one-box race weekend deployment; k8s deferred until multi-session SaaS reality | k8s now (over-engineering) |
| LLM access | OpenAI-compatible adapter interface (configurable base URL/model) | provider-agnostic; local/self-host possible | hard dependency on one vendor |

## 6. Data flow walkthrough (race lap completion, live)

1. `TimingData` frame arrives (~0–2 s after track fact) → ingestion watchdog OK.
2. Normalizer assembles sectors/lap → emits `LapCompleted` (+3 × 
   `SectorCompleted`) canonical events → raw frame already archived.
3. State update: leaderboard, gaps; Redis snapshot throttled-publish.
4. Analyzers: PaceAnalyzer adds sample to rolling windows; TyreAnalyzer updates
   stint series; SectorAnalyzer evaluates purple/PB.
5. Event engine: e.g., `PurpleSectorSet`, `PaceShiftDetected` (rolling-5 delta
   beyond threshold), possibly `UndercutThreat`.
6. Persistence batch-inserts laps/sectors/events.
7. AI engine (for priority ≥ high events): builds pack (≤ ~6 KB) → LLM →
   validated `InsightGenerated` AIEvent (labeled E-class).
8. Gateway pushes envelope `{state.patch?, events[]}` to subscribed sockets.
   End-to-end target: ≤ 3 s p95 from track fact to client.

## 7. Scaling story

- **Vertical first**: one backend comfortably ingests several concurrent
  sessions (per-session tasks are I/O bound; CPU is analysis-light).
- **Gateway horizontal**: stateless readers of Redis pub/sub; add replicas.
- **Session sharding**: if many simultaneous sessions (e.g., all feeder
  series someday), assign sessions to ingestion workers via Redis leases.
- **Storage growth**: monthly partitioning on laps/telemetry; Timescale when
  interactive long-range queries matter.
- **LLM cost**: event-driven calls + caching + budgets keep spend O(tens of
  cents/session) rather than streaming-token disaster.

## 8. Failure modes & degraded operation

| Failure | Behavior |
|---|---|
| Feed disconnect | supervisor reconnect w/ backoff; state marked STALE; UI shows last-good + age; snapshot resync on rejoin |
| Partial topic outage | capability descriptor flips that stream to F-class live; analyzers skip honestly |
| Provider ban/auth change | config switch to OpenF1 sponsor tier without code change |
| DB down | ingest+archive continue (raw frames durable); canonical writes queue and catch up |
| Redis down | single-gateway direct mode (degraded fan-out), auto-recover |
| LLM down/over-budget | platform fully functional minus E-class content; events queued for post-session digest |

## 9. Security

Secrets via env only (`ops/.env.example` template, git-ignored); no secrets in
recordings; WS auth token scheme ready for multi-user phase (MVP: LAN/token
optional); outbound-only connections from ingestion (no inbound ports besides
API); strict pydantic validation at every boundary; dependency pinning +
`pip-audit` in CI.
