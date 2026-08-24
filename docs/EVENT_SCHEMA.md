# EVENT_SCHEMA.md

| | |
|---|---|
| Status | Phase 0 |
| Purpose | Single envelope for all in-process and delivered events |

---

## 1. Envelope

Every event — raw domain, analytical, AI — uses one envelope:

```jsonc
{
  "event_id": "uuid",                 // globally unique
  "seq": 918273,                      // per-session monotonic (bus order)
  "type": "sector.purple_set",        // namespaced, dot-separated
  "category": "domain | derived | ai | system",
  "session_id": "uuid",
  "session_ts": "2026-08-23T14:03:12.480Z",   // session clock
  "wall_ts":   "2026-08-23T14:03:13.102Z",    // processing time
  "priority": 1..5,                   // 1=critical … 5=debug
  "provenance": { "class": "A|B|C|D|E|F", "source": "...", "generator_version": "..." },
  "subjects": { "drivers": ["norris"], "teams": [], "laps": [42] },
  "payload": { ... },                 // schema per type below
  "dedupe_key": "sector.purple_set:sess:norris:S2:41" // idempotency
}
```

Rules:
- Events are immutable; corrections are *new* events (`*.corrected`) referencing
  the original `event_id`.
- `dedupe_key` guarantees at-least-once delivery semantics end-to-end.
- Priority drives UI surfacing and whether AI explanation is triggered.

## 2. Domain events (category=domain, class A/B)

Direct observations after normalization. Payloads reference canonical entities
(DATA_MODEL.md), never vendor shapes.

| type | payload essentials |
|---|---|
| `session.status_changed` | `{ from, to }` (SCHEDULED→LIVE→FINISHED) |
| `session.lap_count_changed` | `{ current, total }` |
| `timing.leaderboard_updated` | `{ entries: [{driver_id, position, gap_s?, interval_s?, lap}] }` (throttled ≤1 Hz) |
| `lap.completed` | full Lap record ref + `{ duration_ms, valid }` |
| `sector.completed` | `{ sector_index, time_ms, status }` |
| `tyre.stint_started / stint_ended` | TyreStint ref |
| `pit.started / pit.completed` | PitStop partial/full |
| `weather.updated` | WeatherPoint |
| `rcm.message` | RaceControlEvent |
| `track_status.changed` | `{ to: GREEN|YELLOW|SC|VSC|RED, rcm_ref }` |
| `driver.status_changed` | `{ driver_id, from, to }` |
| `position.changed` | `{ driver_id, from, to, lap }` |
| `team_radio.published` | `{ driver_id, audio_url, ts }` |

## 3. Derived/analytical events (category=derived, class C/D)

Emitted by the analysis engine through the event engine's debounce/hysteresis.

| type | payload | notes |
|---|---|---|
| `sector.personal_best` | `{ sector_index, prev_best_ms, new_best_ms }` | |
| `sector.purple_set` | `{ sector_index, driver_id, time_ms, prev_holder? }` | priority 3–4 |
| `sector.yellow_sector` | `{ sector_index, drivers[] }` | |
| `lap.deleted` | `{ driver_id, lap_number, reason, rcm_ref }` | tombstone propagation |
| `theoretical_lap.updated` | `{ driver_id, theoretical_ms, delta_to_actual_ms }` | |
| `pace.rolling_updated` | `{ driver_id, windows: {"3":ms,"5":ms,"10":ms}, trend }` | throttled |
| `pace.shift_detected` | `{ driver_id, window:"5", delta_ms_per_lap, cause_hint }` | hysteresis ≥0.3 s/lap sustained 3 laps |
| `pace.clean_air_changed` | `{ driver_id, clean_air: bool }` | |
| `tyre.degradation_alert` | `{ driver_id, stint, slope_ms_per_lap, projected_life_laps }` | class D fields flagged |
| `tyre.warmup_anomaly` | `{ driver_id, expected_vs_observed }` | |
| `strategy.pit_window_open/close` | `{ driver_id, laps:[a,b], model_inputs_ref }` | |
| `strategy.undercut_threat` | `{ attacker, defender, required_delta_ms, window_laps }` | |
| `strategy.overcut_threat` | symmetric | |
| `strategy.sc_window` | `{ eligible_drivers[], pit_loss_delta_ms }` | only during SC/VSC |
| `battle.started / battle.ended` | BattleEvent ref | gap ≤0.7 s for ≥2 consecutive checks |
| `battle.drs_range` | `{ pair, gap_s }` | |
| `battle.closing_rate` | `{ pair, s_per_lap }` | |
| `quali.elimination_risk` | `{ driver_id, part, risk: 0..1, cutoff_delta_ms }` | class D |
| `practice.run_classified` | `{ driver_id, run_type: PUSH\|COOL\|LONG_RUN\|QUALI_SIM\|RACE_SIM, laps[] }` | |
| `track.evolution_jump` | `{ improvement_ms, window_min }` | |
| `weather.condition_change` | `{ rain: bool, track_state_hint }` | |

## 4. AI events (category=ai, class E)

| type | payload |
|---|---|
| `ai.explanation_ready` | `{ insight_id, trigger_event_ids, headline, body_markdown, claims:[{text, evidence_pack_refs[], class}], grounding:{passed} }` |
| `ai.chat_answer_ready` | `{ request_id, answer, claims[], citations[] }` |
| `ai.digest_published` | `{ period:"H1"\|"FULL", report_ref }` |
| `ai.request_failed` | `{ reason, budget_state }` | system-visible degradation |

## 5. System events (category=system)

| type | payload |
|---|---|
| `provider.connected/disconnected` | `{ provider, topics?, error? }` |
| `provider.data_gap` | `{ from_ts, to_ts, channels }` |
| `recorder.frame_archived` | `{ seq }` (low priority, sampling) |
| `replay.state_changed` | `{ speed, position, mode }` |
| `pipeline.health` | `{ lag_ms, queue_depths }` |

## 6. Delivery semantics

- **Internal bus**: asyncio queues; per-subscriber bounded queues with
  backpressure policy = drop-lowest-priority + health event (never block ingest).
- **WS delivery**: batched frames `{ state_patch?, events[] }` every ≤250 ms or
  immediately for priority ≤2; client ack not required; reconnect protocol =
  `state.snapshot` then resume from last `seq`.
- **Ordering**: strict per session by `seq`; clients must tolerate gaps on
  disconnect (snapshot repair covers it).
- **Retention**: events persisted (Postgres) for post-session analytics and AI
  digests; Redis Streams hold rolling 24 h hot window.
