# DATA_PIPELINE.md

| | |
|---|---|
| Status | Phase 1 implementation notes |
| Scope | Ingestion → normalization → canonical events → persistence + recording |

---

## 1. Flow (as implemented)

```
OpenF1 REST API
   │  (rate-limited token bucket, retry/backoff honoring Retry-After)
   ▼
OpenF1Provider.run()                    app/providers/openf1/provider.py
   │  yields RawItem { channel, verbatim payload, source_ts, provenance_class }
   ▼
IngestPipeline.process()                app/ingest/pipeline.py
   │  normalize() dispatch per channel  app/ingest/normalize.py
   │     └─ vendor payload → canonical pydantic models (or NormalizationError)
   │  dedupe via envelope.dedupe_key (in-memory LRU; DB UNIQUE constraints are
   │     the durable second layer)
   │  wraps in Envelope (event_id, seq, timestamps, provenance)
   ▼
EventBus.publish()                      app/core/events.py
   │  deterministic inline fan-out (subscriber isolation: one failure never
   │     kills ingestion)
   ├─▶ Recorder                          app/ingest/recorder.py
   │     recordings/<name>/frames.jsonl.zst  (+ meta.json, quality.json)
   └─▶ PersistenceSubscriber             app/ingest/persistence.py
         batched inserts → PostgreSQL    app/storage/db.py + migrations/
```

Replay uses the SAME path: `ReplayProvider` reads the recording and yields
RawItems carrying `__envelope`; `normalize()` recognizes pre-canonical frames
and passes them through untouched (origin=replay). Verified empirically: a
full database rebuild from the recording alone produced row counts identical
to live ingestion.

## 2. Channels and dedupe keys

| Channel | Canonical model(s) | Event type(s) | Dedupe key |
|---|---|---|---|
| SESSION_META | SessionInfo | session.discovered | session:{provider}:{key} |
| DRIVER_LIST | Driver (+Team) | driver.detected, team.detected | driver:{driver_id} / team:{team_id} |
| LAP | Lap + 3×SectorTime | lap.completed, sector.recorded | lap:{sid}:{num}:{lap} / sector:+":S{i}" |
| CAR_DATA | TelemetryCarSample | telemetry.car_sample | car:{sid}:{num}:{ts} |
| LOCATION | TelemetryLocationSample | telemetry.location_sample | loc:{sid}:{num}:{ts} |
| STINT | TyreStint | tyre.stint_recorded | stint:{sid}:{num}:{stint_no} |
| PIT | PitStop | pit.recorded | pit:{sid}:{num}:{ts} |
| WEATHER | WeatherPoint | weather.updated | wx:{sid}:{ts} |
| RACE_CONTROL | RaceControlEvent | rcm.message | rcm:{sha256(second\|message)} |
| POSITION | PositionUpdate | position.changed | pos:{sid}:{num}:{ts} |
| INTERVALS | TimingInterval | timing.interval_updated | iv:{sid}:{num}:{ts} |

## 3. Timestamp rules

- `source_timestamp` = upstream record timestamp (never altered).
- `ingestion_timestamp` = UTC time our pipeline processed the frame.
- Latency = ingestion − source; measured continuously by the quality monitor.
- Replay preserves BOTH original values and flags origin=replay so latency
  stats are never polluted.

## 4. Backfill strategy (historical mode)

- Cursors seeded at `session_start − 45 min` (NOT epoch — early bug walked
  decades of empty windows).
- High-rate channels (car_data/location) sweep bounded 10-min windows;
  low-volume channels (laps/pit/weather/rcm/position/intervals) make ONE
  ranged call per sweep.
- Termination: all cursors past `session_end + 30 min`, or safety cap (600
  rounds).
- Live mode: same loop, no upper bounds, sleeps poll_interval between sweeps.

## 5. Error handling contract

| Condition | Behavior |
|---|---|
| Malformed record | dropped, counted (`malformed_events`), WARNING logged with reason — pipeline continues |
| Duplicate | suppressed at pipeline AND DB layer, counted |
| HTTP 429 / 5xx | exponential backoff honoring Retry-After (max 6 attempts) then channel skipped for that sweep |
| Empty results | OpenF1 signals "no data" as HTTP 200 **or 404** with `{"detail":"No results found."}` — both treated as [] (verified quirk) |
| Network failure | reconnect counter incremented, retried with backoff |
| Subscriber crash | isolated by bus; logged; ingestion unaffected |

## 6. Recording format v1

```
recordings/<provider>-<session_key>-<type>/
├── meta.json        session snapshot, provider, frame count, format tag
├── frames.jsonl.zst one JSON line per frame:
│                     {"seq": N, "envelope": {…canonical envelope…}}
└── quality.json     final DataQualityMonitor report
```

zstd-compressed append-only JSONL. The recording is the replay source of
truth; a full DB rebuild from it was verified byte-count-identical per channel
(see §7).

## 7. Verified acceptance numbers (2026 Dutch GP, session 11353)

Live-path ingest: **1,067,193 events** published, 0 malformed, DB rows =
domain counts below. Replay-path rebuild from recording: identical counts,
+1,066,829 event-audit rows (origin=replay).

| Table | Rows |
|---|---|
| laps | 1,369 |
| sectors | 4,107 |
| telemetry_car | 530,166 |
| telemetry_location | 499,290 |
| tyre_stints (unique) | 87 |
| pit_stops | 65 |
| weather_points | 183 |
| race_control_messages | 329 |
| position_updates | 586 |
| timing_intervals | 30,613 (incl. 8,629 gap_raw='+1 LAP') |
