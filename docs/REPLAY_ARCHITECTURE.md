# REPLAY_ARCHITECTURE.md

| | |
|---|---|
| Status | Phase 0 |
| Prime directive | Replay is live with a different clock. One pipeline, one interface. |

---

## 1. Design goals

1. Any recorded session replays **as if live** — same analyzers, same events,
   same AI pipeline, same WS contract.
2. Deterministic: replaying the same recording yields identical derived state
   and identical event sequence (parity test in CI).
3. Recording starts on day one (Phase 2), even though the replay UI ships later.
4. Scrubbing: seek backward = rebuild state by folding frames from session
   start (fast path: nearest snapshot + incremental fold); seek forward =
   accelerated fold, no LLM calls until playback settles.

## 2. What gets recorded (two tiers)

| Tier | Content | Format | Purpose |
|---|---|---|---|
| Raw archive | provider payloads verbatim + receipt wall-ts | `raw-{provider}-{session}.jsonl.zst` | re-parse when normalizer improves; forensic debugging |
| Canonical recording | normalized `ReplayFrame` stream (EVENT_SCHEMA channels) | `frames-{session}.jsonl.zst` + index rows in PG | the replay source |

Canonical recording is authoritative for replay; raw tier exists because our
normalizer will have bugs and upstream formats drift. Both are written
append-only during ingestion with fsync batching (~1 s) — a crash loses ≤1 s.

Frame index (PG): `(session_id, seq, channel, session_ts, byte_offset)` every
Nth frame + per-channel first/last seq → O(1) positioning for seeks.

## 3. Clock service

```
ClockService (interface)
├── LiveClock        anchored to wall time; Heartbeat/ExtrapolatedClock corrects drift
└── ReplayClock      virtual; speed ∈ {0(pause),0.25..16,MAX(fold)}; seek(ts); source=ReplayProvider
```

Everything downstream consumes `clock.now_session_ts()`. No component reads
wall-clock for logic ordering (wall-ts is metadata only). This single rule is
what makes parity achievable.

## 4. ReplayProvider

Implements `ProviderPort` identically to live providers:

```python
class ReplayProvider:
    async def run(self, session_id):            # emits canonical frames
    def capabilities(self) -> Capabilities      # from recording metadata
```

- Reads `.jsonl.zst` sequentially, paces frames against ReplayClock.
- `capabilities()` honestly reports what the recording contains (e.g., a
  session recorded before telemetry archiving shows telemetry=F-class).
- Gaps carry explicit `provider.data_gap` events so UI can show "recording
  gap" rather than silently stalling.

## 5. State snapshots & seeking

SessionState supports `snapshot()` / `fold(frame)` (pure-ish incremental
reducer). Snapshots persisted periodically during live (every ~60 s of session
time + at every track-status change) into object storage keyed
`(session_id, seq)`. Seek algorithm:

1. Find latest snapshot ≤ target seq.
2. Fold subsequent canonical frames to target.
3. Publish fresh `state.snapshot`; resume streaming.

Backward seek beyond earliest available snapshot folds from frame 0 (bounded,
recordings ≪ millions of frames).

## 6. Events & AI during replay

- Detected events regenerate naturally during fold; they are tagged
  `origin=replay` and NOT re-persisted over live-recorded equivalents
  (`dedupe_key` collision-safe).
- Persisted historical AIEvents attach to their trigger timestamps → replay UI
  shows original insights at original moments ("as-analyst-then" mode).
- Optional "re-analyze with current models" mode recomputes analyzers/AI on
  demand, stored as separate model-versioned runs. Never mixes versions within
  one view.

## 7. Parity guarantee & CI

Test: record 30 min of any session → hash final SessionState + event list via
(a) live pass, (b) replay pass of the canonical recording ⇒ hashes must match
modulo metadata fields (wall_ts, origin tags). Runs in CI weekly against a
fixture corpus of ≥3 recordings (different session types).

## 8. Delay/buffer mode (live)

The same machinery provides intentional delay (e.g., +30 s broadcast sync):
LiveClock feeds ReplayClock offset — implemented as trivial wrapper, not a
separate system.

## 9. Storage sizing (planning numbers)

Per race session estimate: timing+telemetry+position canonical JSONL zstd ≈
40–90 MB/session compressed (measure precisely in Phase 2; adjust retention).
Raw tier similar magnitude. A full season ≈ low GBs — local/object storage
trivially sufficient; no exotic infra justified.
