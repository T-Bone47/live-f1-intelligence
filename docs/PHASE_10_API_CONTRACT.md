# PHASE 10 — API CONTRACT

> Design only — nothing in this document has been implemented. Proposed
> throughout, built directly on the verified findings in the other four
> Phase 10 documents, not invented independently of them.

## The core design decision: REST, not WebSocket

The flagship comparison (2 drivers, 1 lap) is a **bounded historical
query** — everything needed exists the moment the request is made; there
is nothing to stream incrementally. This is a different shape of request
from everything the existing WS contract (`SNAPSHOT`/`DELTA`/`EVENTS`/
`TELEMETRY`/`CONTROL`/`PONG` frame kinds) was built for, which is
live/replay-as-a-feed. A plain REST `GET` fits this correctly. The
existing WS `TELEMETRY` frame kind is untouched by this proposal — it
remains what it is, for live viewing.

## New endpoint

```
GET /api/v1/sessions/{session_id}/laps/{lap_number}/telemetry?drivers=1,44
```

A purpose-built, lap-scoped, multi-driver endpoint — not an overload of
the existing `/telemetry/{driver}` endpoint, which serves a genuinely
different use case (whole-session, time-range, LTTB-downsampled, single
driver, already correctly built for the existing `TelemetryLab`
workspace). Requesting both drivers in one call avoids the round-trip
and clock-skew risk of two separate requests.

**Response shape (proposed):**
```json
{
  "session_id": "openf1:...",
  "lap_number": 5,
  "distance_axis": "percent_of_lap",
  "drivers": {
    "1": {
      "available": true,
      "lap_time_s": 78.234,
      "is_pit_out_lap": false,
      "deleted": false,
      "samples": [
        {
          "distance_pct": 0.0,
          "speed_kph": 312.0,
          "throttle_pct": 100,
          "brake_pct": 0,
          "gear": 8,
          "rpm": 11800,
          "drs": 10,
          "confidence": "OBSERVED"
        }
      ]
    },
    "44": { "...": "same shape" }
  }
}
```

`confidence` per sample is `OBSERVED`, `INTERPOLATED` (within the normal
gap threshold), or `ESTIMATED` (beyond it) — matching the honest-
degradation design in `PHASE_10_LAP_SYNCHRONIZATION.md`, not a single
blanket confidence value for the whole response. `deleted` is always
`false` today (the field is real but never set anywhere in this
codebase, per that same document) — the response should say so plainly
rather than omit the field, so a client can't mistake its absence for a
guarantee of validity.

**A driver with `available: false`** (no persisted telemetry for that
lap — e.g., before the persistence wiring fix lands, or a genuine data
gap) returns that plainly, with no `samples` array, rather than an empty
array that could be misread as "zero-speed, zero-throttle for the whole
lap."

## Dependency on the architecture document

This endpoint has exactly one hard prerequisite: `PersistenceSubscriber`
attached to the envelope stream (architecture doc §4). Without it, this
endpoint would be correctly built but permanently return
`available: false` for every request — the same situation
`/telemetry/{driver}` is in today, discovered this phase, not assumed.

## Circuit geometry: extend, don't duplicate

The existing `/circuit` endpoint already exists and honestly returns
`available: false` (Phase 9 finding). Once external-geometry calibration
(`PHASE_10_LAP_SYNCHRONIZATION.md`) is built, the natural extension is
to that same endpoint — adding the geometry payload plus a calibration-
confidence field — rather than a new endpoint. No proposal to change its
shape further than that in this phase.

## What does not change

- `/telemetry/{driver}` — untouched, different use case.
- The WS `TELEMETRY` frame kind and `TelemetryCoalescer` — untouched,
  remain the live-viewing path.
- `/circuit` — extended later, not replaced.
