# DECISIONS.md

| | |
|---|---|
| Status | Phase 0 — living document; every major decision gets an entry |

Format: Decision / Context / Rationale / Consequences / Alternatives.

---

## D1 — Primary live source: direct signalrcore feed; OpenF1 paid as fallback

**Decision**: `LiveTimingProvider` (direct, wss://livetiming.formula1.com/signalrcore)
is primary; OpenF1 sponsor tier is secondary; both behind one interface.
**Context**: Direct feed = lowest latency (~0–2 s), richest topics
(mini-sector segments, traps), free today — but auth posture unstable.
OpenF1 = contractual-ish stability + MQTT/WS, ~3 s, €9.90/mo.
**Consequences**: we maintain a SignalR Core client; auth is pluggable;
capability descriptors differ per provider and must propagate.
**Alternatives**: OpenF1-only (single point of failure + latency floor);
scraping third-party dashboards (dependency on fan infra + AGPL).

## D2 — Python/FastAPI backend, not Rust/Node

**Decision**: single Python 3.12 service (FastAPI + uvicorn).
**Rationale**: ecosystem gravity (FastF1 validation oracle, OpenF1 tooling,
pandas/numpy analytics); volumes are tiny (<200 msg/s) so Rust's perf edge buys
nothing; hiring/iteration speed favors Python. Node rejected on numerics;
Rust revisited only if a gateway rewrite ever needs 10k+ concurrent WS clients.
**Consequences**: GIL irrelevant at our concurrency profile (I/O bound);
analytics must avoid pandas in the hot path (numpy buffers/dataclasses).

## D3 — No Kafka/NATS for MVP

**Decision**: asyncio queues internally; Redis Streams at process boundaries.
**Rationale**: single-host deployment, trivial throughput; message brokers add
ops burden without benefit yet. Bus interface (`events/bus.py`) is narrow so a
broker can slot in later if multi-process ingestion arrives (Phase 7 trigger).
**Alternatives**: NATS JetStream (lighter than Kafka but still another server).

## D4 — PostgreSQL now; TimescaleDB/ClickHouse deferred

**Decision**: plain PG16 schema per DATA_MODEL.md; batched inserts; monthly
partitions when needed.
**Rationale**: ~150 telemetry rows/s peak is nothing for PG; canonical
relational integrity matters more than columnar analytics pre-Phase-7.
Timescale remains drop-in-compatible (hypertables over same tables).
ClickHouse reconsidered only if long-range multi-season analytics becomes a
product pillar.

## D5 — Two-tier recording: raw archive + normalized ReplayFrame stream

**Decision**: record provider payloads verbatim AND canonical normalized
frames; replay consumes canonical tier.
**Rationale**: raw protects against normalizer bugs/format drift (re-parse
forever); canonical makes replay provider-agnostic and parity-testable.
Cost ≈ double storage of small files — negligible (REPLAY_ARCHITECTURE.md §9).

## D6 — LLM access strictly via context packs + structured claims

**Decision**: as AI_ARCHITECTURE.md — packs ≤~8 KB, claims with evidence refs,
validator-enforced numeric equality, class-E labeling.
**Rationale**: charter rules 6 & 11; hallucination containment by construction
(R8). **Alternative rejected**: RAG-over-telemetry ("let the model query") —
non-deterministic cost and unbounded latency during live sessions.

## D7 — Mode profiles are config, not code branches

**Decision**: session-type behavior lives in versioned YAML profiles
(SESSION_MODES.md §1) selecting analyzers/thresholds/surfaces.
**Rationale**: F1 keeps changing formats (sprint revisions); new formats should
be a data change + tests, not a refactor.

## D8 — Monorepo, single deployable backend (+ frontend later)

**Decision**: one repo, one backend container (+ pg/redis compose), Next.js
frontend added Phase 6 in same repo.
**Rationale**: charter rule 8; shared pydantic models → generated TS types keep
contract honest; monorepo avoids version-skew during rapid iteration.

## D9 — Provenance classes are a type-level concern, not documentation

**Decision**: `provenance` fields exist in schemas, DB rows, WS envelopes, UI
props. Renderers refuse unlabeled derived values (lint rule in frontend).
**Rationale**: charter rule 11 enforced mechanically beats good intentions.

## D10 — Non-commercial posture until licensing changes

**Decision**: no paywalls, no ads, no raw-data resale; attribution pages;
takedown-ready ops. See DATA_SOURCES.md §9.
**Consequences**: constrains hosting choices (no aggressive commercial
platforms required anyway) and future monetization paths without licensed data.

## D11 — Auth: optional bearer tokens MVP; RBAC later

**Decision**: env-listed API tokens; anonymous read permitted on trusted
deployments; user accounts deferred to post-MVP backlog.
**Rationale**: single-user/small-team reality now; contract already shaped for
tokens so adding identity later is additive.

## D12 — Repo structure proposal

```
live-f1-intelligence/
├── docs/                        # this Phase-0 set + future ADRs
├── backend/
│   ├── app/
│   │   ├── providers/
│   │   │   ├── base.py          # ProviderPort, Capabilities
│   │   │   ├── livetiming/      # signalr core client, auth strategies
│   │   │   ├── openf1/          # rest+mqtt adapters, backfill
│   │   │   └── jolpica/         # schedule/results sync
│   │   ├── ingest/              # supervisors, raw archiver, recorder
│   │   ├── normalize/           # vendor→canonical transforms (pure)
│   │   ├── core/
│   │   │   ├── models/          # canonical pydantic schemas (DATA_MODEL)
│   │   │   ├── state.py         # SessionState fold/snapshot
│   │   │   └── clock.py         # LiveClock / ReplayClock
│   │   ├── analysis/            # sector/pace/tyre/battle/strategy/weather/quali/practice
│   │   ├── events/              # envelope, bus, detectors, dedupe
│   │   ├── ai/                  # packs, templates/, llm_adapters/, grounding, eval/
│   │   ├── storage/             # pg repo layer, redis, archives, migrations/
│   │   ├── api/                 # routers, ws gateway, sse
│   │   └── config.py
│   ├── tests/                   # unit + fixtures + parity + chaos
│   └── pyproject.toml
├── frontend/                    # Phase 6 placeholder
├── tools/                       # record_cli, replay_cli, fixture_harvester, eval_runner
├── ops/                         # docker-compose.yml, .env.example, grafana/ (Phase 7)
├── fixtures/                    # recordings (LFS/local), golden expected outputs
├── modes.yaml                   # SESSION_MODES profiles
└── README.md
```

**Rationale**: mirrors pipeline order left-to-right; providers isolated at the
edge where vendor code belongs; pure normalize/ enables property-based tests;
fixtures first-class because replay/AI-eval depend on them.

## Deferred decisions (recorded, intentionally open)

| ID | Topic | Trigger to revisit |
|---|---|---|
| DD1 | TimescaleDB adoption | interactive multi-season queries needed |
| DD2 | Message broker | multi-process ingestion or >1 host workers |
| DD3 | Mini-sectors from own track maps | after Phase 6 track-map work |
| DD4 | Team-radio STT | Phase 7 experiment gate |
| DD5 | Multi-region deployment | actual geographic user base |
| DD6 | Frontend framework final call | Phase 6 kickoff (Next.js default unless blocked) |
