# REALTIME_ARCHITECTURE.md

| | |
|---|---|
| Status | Phase 3 |
| Core invariant | The WebSocket layer DELIVERS; it never computes. |

---

## 1. Topology

```
ONE upstream per session (OpenF1 | SignalR | ReplayProvider)
        │  RawItem stream
        ▼
IngestPipeline  ── raw/canonical recording (unchanged)
        │  canonical envelopes on EventBus
        ▼
AnalysisEngine  (Phase-2 engines, provider-independent)
        │  IntelligenceEvents via listener callbacks
        ▼
SessionHub  (app/realtime/hub.py)
   ├─ SnapshotDiffer      250 ms publish loop
   ├─ SequenceHistory     monotonic seq + 2000-frame resume ring
   ├─ TelemetryCoalescer  per-driver latest-wins (5 Hz default)
   └─ per-client bounded queues (400) with documented backpressure
        ▼
FastAPI  /ws/session/{id}  +  /api/v1/* REST
        ▼
Client A … Client N          (Redis transport optional for scale-out)
```

Single-upstream guarantee: `HubRegistry` holds at most one SessionHub per
session — one OpenF1/SignalR connection serves unlimited clients.

## 2. Frame kinds

| kind | purpose | batching |
|---|---|---|
| snapshot | full projection on connect / unresumable gap | immediate |
| delta    | dotted-path changes since last publish | ≤250 ms |
| events   | intelligence events | non-critical piggybacked on deltas; **critical types sent immediately** |
| telemetry | coalesced per-driver samples | per-subscription cadence (5 Hz default) |
| control / pong | subscription acks, keepalive | immediate |

Critical set: SAFETY_CAR, VSC, RED_FLAG, SESSION_STATE_CHANGE, OVERTAKE,
FASTEST_LAP_CHANGE, plus any severity IMPORTANT/CRITICAL.

## 3. Backpressure policy (never block the pipeline)

Per-client queue = 400 frames.
- Publisher is always non-blocking.
- DELTA/TELEMETRY onto a full queue → frame dropped FOR THAT CLIENT, counted.
- SNAPSHOT/EVENTS onto a full queue → client EVICTED (sentinel + close).
  Critical frames are never silently lost; a too-slow client reconnects and
  resumes by sequence.
Metrics: `deltas_dropped_slow_clients`, `slow_client_evictions`.

## 4. Redis

Optional (`REDIS_URL`). When absent everything runs in-process — development
needs no Redis. When present, the hub's outbound frames are additionally
published to `f1intel:{session}` channels so stateless gateway replicas can
fan out (implementation slot: `realtime/redis_transport.py`, Phase 4 as
measured need arises). PostgreSQL remains the only durable store; Redis never
holds canonical persistence.

## 5. Replay-as-realtime

`serve_realtime.py --mode replay <recording>` drives the IDENTICAL hub:
ReplayProvider → pipeline → analysis → diffs → WS. Playback speed scales the
replay clock (0.25×–max). Clients cannot distinguish live from replay except
by `session_id` prefix and provider status field.

## 6. Observability

`GET /api/v1/live-data-status` returns per-hub: provider name/status/reconnects,
events/sec, analysis/snapshot/diff latency percentiles, diff size p50,
WS clients + broadcast latency percentiles, slow-client counters, Redis state,
uptime. Sources: hub metrics + ingest quality monitor (provider latency p50/p95
when class-A samples exist).

## 7. Measured results (this phase)

See SCALING.md for the full ladder; summary on the Dutch GP recording,
single process, Windows workstation:

| Clients | OK | Aggregate frames/s | WS p50 latency | Drops | Evictions |
|---|---|---|---|---|---|
| 10 | 10 | 70 | 14.9 ms | 0 | 0 |
| 50 | 50 | 395 | 79.0 ms | 0 | 0 |
| 100 | 100 | 994 | 129.7 ms | 0 | 0 |

CPU ~95% in all runs because max-speed replay ingest shares the event loop;
real live rates (~200 msg/s peak) leave >30× headroom. Latency grows
linearly with fanout under saturation — the documented scaling signal that
would trigger gateway replication + Redis first.
