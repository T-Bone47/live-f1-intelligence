# WEBSOCKET_API.md

| | |
|---|---|
| Endpoint | `ws://host:port/ws/session/{session_id}` |
| Protocol | `f1intel-snapshot-1` (every frame carries it) |

---

## 1. Connect

On connect the server immediately sends a FULL snapshot frame, then deltas.
No authentication is required in trusted-network mode; bearer-token support
is wired for deployment (`API_TOKENS` env).

## 2. Frames (server → client)

```jsonc
// full snapshot (connect / unresumable resume)
{ "kind": "snapshot", "session_id": "...", "seq": 41,
  "ts": "2026-08-23T15:00:00.100+00:00",
  "schema": "f1intel-snapshot-1", "data": { ...SessionSnapshot... } }

// delta
{ "kind": "delta", "session_id": "...", "seq": 42, "ts": "...",
  "schema": "f1intel-snapshot-1",
  "changes": { "leaderboard.1.last_lap_s": 74.9,
               "weather.air_temp_c": 19.1 },
  "removed": ["battles.4v12"],
  "events": [ /* non-critical IntelligenceEvents piggybacked */ ] }

// critical events (immediate)
{ "kind": "events", "seq": 43, "critical": true,
  "events": [ { "event_type": "SAFETY_CAR", ... } ] }

// telemetry (only for subscribed drivers)
{ "kind": "telemetry", "seq": 44, "driver": 16,
  "samples": [ { "ts": "...", "speed_kph": 288, "rpm": 11400,
                 "gear": 7, "throttle_pct": 100, "brake_pct": 0,
                 "drs": 8, "x": -1421, "y": 5200, "z": 1200 } ] }

// errors / lifecycle
{ "kind": "error" | "evicted" | "pong", ... }
```

Client-side gap detection: keep `last_seq`; on receiving seq > last_seq+1 a
gap occurred → send resume; duplicate/lower seq → stale update, ignore.

## 3. Frames (client → server)

```jsonc
{ "action": "ping" }                                   // -> pong + server_time
{ "action": "resume", "last_seq": 40 }
{ "action": "subscribe", "drivers": [16, 55],          // restrict delta scope
  "telemetry_drivers": [16], "deltas": true }          // optional toggles
```

Unknown actions receive `{"kind":"error","detail":...}` and stay connected.

## 4. Resume semantics

- `since(last_seq)` replays retained history frames (ring of 2000).
- If `last_seq` predates the ring or is unknown → fresh full snapshot with a
  new sequence. Clients must treat any snapshot frame as authoritative state
  replacement.

## 5. Slow clients

Queue overflow drops pending deltas/telemetry for that client (counted);
overflow by critical frames evicts the client: server sends
`{"kind":"evicted"}` where possible then closes. Reconnect + resume restores
continuity.

## 6. REST companions (same canonical schemas)

```
GET /api/v1/live-data-status
GET /api/v1/sessions
GET /api/v1/sessions/{id}/snapshot | /drivers | /leaderboard | /events?limit=
GET /api/v1/sessions/{id}/sectors/{driver} | /tyres/{driver} | /pace/{driver}
GET /api/v1/sessions/{id}/telemetry/{driver}     # streaming guidance
GET /api/v1/health
```
Rate limit: 120 req/min per client IP (429 beyond). Session ids validated
(length ≤64, no path characters). No provider-specific shapes are exposed
anywhere.
