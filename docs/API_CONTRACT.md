# API_CONTRACT.md

| | |
|---|---|
| Status | Phase 0 |
| Versioning | `/api/v1/...`; additive changes only within v1; breaking → v2 |
| Transport | REST (JSON) + WebSocket (primary) + SSE (fallback) |

---

## 1. Conventions

- All timestamps ISO-8601 UTC.
- Every resource embeds `provenance` where values can be derived/predicted
  (`class: A..F`, `source`, `confidence?`).
- Missing data = absent field or explicit `null` + `available:false` — never
  fabricated defaults.
- Errors: `{ "error": { "code": str, "message": str, "details"? } }`.
- Pagination: cursor-based (`?cursor=&limit=`, default 100, max 1000).

## 2. REST endpoints (v1)

### Sessions & catalog
```
GET  /api/v1/sessions?season=&type=&status=         # list, Jolpica-backed schedule merged w/ ours
GET  /api/v1/sessions/{session_id}                  # detail incl. capabilities descriptor
GET  /api/v1/sessions/{session_id}/drivers          # SessionDriver[]
GET  /api/v1/sessions/{session_id}/state            # full snapshot (cold start / repair)
```

### Timing & laps
```
GET  /api/v1/sessions/{id}/laps?driver_id=&from_lap=&to_lap=
GET  /api/v1/sessions/{id}/laps/{lap_number}?driver_id=
GET  /api/v1/sessions/{id}/sectors?driver_id=       # SectorTime[] incl. theoretical lap view
GET  /api/v1/sessions/{id}/leaderboard              # computed ordering + gaps at ts (?at=)
```

### Tyres, pits, strategy
```
GET  /api/v1/sessions/{id}/stints?driver_id=
GET  /api/v1/sessions/{id}/pitstops
GET  /api/v1/sessions/{id}/strategy/scenarios       # current model output (class D labeled)
```

### Telemetry
```
GET  /api/v1/sessions/{id}/telemetry/car?driver_id=&from_ts=&to_ts=&fields=speed,throttle,...
     # downsampled server-side (LTTB) when range large; raw ≤5 min per request
GET  /api/v1/sessions/{id}/telemetry/compare?a=&b=&lap_a=&lap_b=   # aligned overlay payload
GET  /api/v1/sessions/{id}/telemetry/location?driver_id=&from=&to= # GPS path samples
```

### Race control, weather, battles
```
GET  /api/v1/sessions/{id}/race-control             # RaceControlEvent[]
GET  /api/v1/sessions/{id}/weather
GET  /api/v1/sessions/{id}/battles                  # BattleEvent[] (live+historical)
```

### AI
```
POST /api/v1/sessions/{id}/ai/chat        { question } -> { answer_id }   # async; poll/WS delivery
GET  /api/v1/ai/answers/{answer_id}
GET  /api/v1/sessions/{id}/ai/insights?since_seq=      # AIEvent feed
GET  /api/v1/ai/answers/{answer_id}/context-pack       # audit access to exact pack sent
```

### Replay control
```
POST /api/v1/replay/{session_id}/start   { speed?: float=1.0, from?: ts|seq }
POST /api/v1/replay/{session_id}/control { action: pause|resume|seek, target?, speed? }
GET  /api/v1/replay/{session_id}/status
GET  /api/v1/recordings                                  # available canonical recordings
```

### System
```
GET  /api/v1/health                                      # liveness
GET  /api/v1/status                                      # provider states, pipeline lag, budgets
```

## 3. WebSocket protocol

`GET /ws/v1/live/{session_id}` (also serves replay sessions; identical wire
format; replay control via REST above).

Client → server:
```jsonc
{ "action":"subscribe",   "topics":["timing","sectors","tyres","weather",
                                     "race_control","battles","strategy","ai","system"] }
{ "action":"unsubscribe", "topics":[...] }
{ "action":"resume",      "last_seq": 918273 }        // gap repair
{ "action":"ping" }
```

Server → client:
```jsonc
{ "kind":"snapshot",  "seq":N, "state": { ...SessionSnapshot } }
{ "kind":"batch",     "seq":N, "events":[ Envelope... ], "state_patch"?: {...} }
{ "kind":"error",     "error": {...} }
{ "kind":"pong",      "server_time": "..." }
```

Rules:
- Batches flushed ≤250 ms; priority ≤2 events flush immediately.
- `state_patch` is a JSON-Merge-Patch style diff of the snapshot for cheap
  client hydration; full snapshots on subscribe/resume-after-gap.
- Server sends `kind:"batch"` with empty events as heartbeat every 15 s.

Topic → event-type mapping table ships with the generated OpenAPI/asyncapi doc
(Phase 4 artifact).

## 4. SSE fallback

`GET /sse/v1/live/{session_id}?topics=...` emits the same batch objects,
`text/event-stream`. For constrained clients; no resume-by-seq (reconnect =
snapshot).

## 5. Auth model

MVP: optional bearer token (`API_TOKENS` env, comma list); unauthenticated
read allowed in trusted-network deployments. WS uses `?token=` or header.
Multi-user/RBAC deferred (documented decision DECISIONS.md D11).

## 6. OpenAPI & codegen

FastAPI generates OpenAPI 3.1 from pydantic canonical models — the same models
used internally, guaranteeing docs ≡ behavior. Frontend (Phase 6) consumes
generated TS types from the spec.
