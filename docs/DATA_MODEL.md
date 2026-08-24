# DATA_MODEL.md

| | |
|---|---|
| Status | Phase 0 |
| Rule | These canonical schemas are the ONLY interchange format above `providers/`. Provider payloads never leak. |

Conventions: all timestamps UTC (`timestamptz` / ISO-8601). Every persisted
row carries provenance:

```json
"provenance": { "source": "livetiming|openf1|jolpica|derived|model|llm",
                "class": "A|B|C|D|E|F",
                "recorded_at": "...Z" }
```

IDs: `session_key` (provider-neutral, we mint ours; mapping table keeps vendor
keys), driver identified by stable `driver_id` (slug) + season-scoped
`driver_number`.

---

## 1. Session

```ts
Session {
  session_id: uuid
  meeting_key: string          // our weekend id
  season: int                  // 2026
  round: int | null            // championship round (null for testing)
  official_name: string
  circuit: CircuitRef          // see §3
  session_type: enum           // PRACTICE_1..3 | QUALIFYING | SPRINT_QUALI | SPRINT | RACE
  mode_profile: enum           // PRACTICE | QUALIFYING | SPRINT | RACE  (SESSION_MODES.md)
  scheduled_start: timestamptz | null
  actual_start: timestamptz | null
  end_time: timestamptz | null
  lap_count: int | null        // races
  status: enum                 // SCHEDULED | LIVE | FINISHED | ARCHIVED | UNKNOWN
  data_window: { first_frame_at, last_frame_at } | null
  provider_refs: jsonb         // { openf1_session_key, livetiming_archive, ... }
}
```

## 2. Driver & Team

```ts
Team   { team_id: slug, name: string, short_name: string(3), color_hex: string,
         season: int }
Driver {
  driver_id: slug              // e.g. "norris"
  permanent_number: int | null
  full_name: string, first_name, last_name, tla: string(3)
  country_code: string(3) | null
  season_entries: [{ season, team_id, number }]     // history via Jolpica/F1DB
}
SessionDriver {                // per-session join w/ live facts
  session_id, driver_id, team_id, number: int,
  position: int | null, status: enum  // ON_TRACK | PIT | OUT(LAP) | IN_GARAGE | RETIRED | DNS | DNF
  retired_lap: int | null
}
```

## 3. Circuit (reference)

```ts
Circuit { circuit_id: slug, name: string, locality: string, country: string,
          length_m: float | null, corner_count: int | null,
          track_map: jsonb | null }   // normalized centerline for GPS→lap-distance mapping (Phase 6)
```

## 4. Lap

```ts
Lap {
  session_id, driver_id
  lap_number: int              // session-wide counter from feed
  started_at: timestamptz      // crossing line
  duration_ms: int | null      // null while in-progress
  sector_times_ms: [int|null, int|null, int|null]
  is_valid: boolean = true
  deleted: boolean = false     // tombstone via RCM (track limits)
  deleted_reason: string | null
  is_out_lap / is_in_lap: boolean | null
  tyre_compound: CompoundCode | null   // denormalized at lap time
  tyre_age_laps: int | null
  track_status: TrackFlagState | null // GREEN/YELLOW/SC/VSC/RED at completion
  traffic_flag: boolean | null         // C-class heuristic (nearby cars within Δ)
  speed_traps_kph: { i1?: float, i2?: float, fl?: float, st?: float }
  provenance
}
unique(session_id, driver_id, lap_number)
```

## 5. Sector (per-lap split detail)

```ts
SectorTime {
  session_id, driver_id, lap_number
  sector_index: 1|2|3
  time_ms: int | null
  is_personal_best: boolean
  is_session_best: boolean     // purple
  status: enum                 // IMPROVED | MAINTAINED | WORSE | YELLOW_SECTOR | DELETED
  recorded_at: timestamptz
  provenance
}
// TheoreticalBestLap (derived view, not stored row):
//   sum of each driver's best valid sectors in session → recomputed on PB change.
```

## 6. TelemetryPoint

```ts
TelemetryPoint {              // one car, one instant (~3.5 Hz)
  session_id, driver_id
  ts: timestamptz              // feed timestamp
  session_time_s: float        // monotonic session clock
  speed_kph: int
  rpm: int
  gear: int                    // -1 unknown / 0 neutral convention documented
  throttle_pct: 0..100
  brake_pct: 0..100            // 0/100 binary upstream — documented as such
  drs: DRSState                // OFF|ENABLED_IN_ZONE|... (raw int mapped)
  x: float | null, y: float | null, z: float | null   // Position.z sample (may arrive interleaved)
  lap_distance_m: float | null // C-class: requires track_map alignment (Phase 6); null until then
  provenance                   // class A/B always
}
// Storage: batch-inserted; partitioned by session. ~150 rows/s peak fleet-wide.
```

## 7. TyreStint

```ts
TyreStint {
  session_id, driver_id
  stint_number: int            // 0-based (stint 0 may be formation/setup laps)
  compound: enum               // SOFT|MEDIUM|HARD|INTERMEDIATE|WET|UNKNOWN(=test/"slick" upstream)
  is_new_tyre: boolean | null
  start_lap: int, end_lap: int | null
  laps_completed: int | null
  start_ts / end_ts: timestamptz | null
  // derived (C/D), stored as columns with own provenance:
  avg_pace_ms: int | null      // outlier-filtered clean-lap mean
  degradation_ms_per_lap: float | null   // slope of robust linear fit
  degradation_trend: enum | null         // STABLE|RISING|SHARP
  warmup_laps: int | null
  projected_life_remaining_laps: int | null   // class D
}
```

## 8. PitStop

```ts
PitStop {
  session_id, driver_id
  stop_number: int
  lap_number: int
  pit_in_ts: timestamptz | null    // from TimingData pit flag transitions
  pit_out_ts: timestamptz | null
  stationary_ms: int | null        // TimingAppData reported
  lane_total_ms: int | null        // derived C: GPS/timing entry→exit
  compound_from / compound_to: CompoundCode | null
  reason_hint: enum | null         // PLANNED | SC_WINDOW | DAMAGE | PENALTY (heuristic, class C)
}
```

## 9. WeatherPoint

```ts
WeatherPoint {
  session_id
  ts: timestamptz
  air_temp_c: float, track_temp_c: float
  humidity_pct: float
  pressure_hpa: float | null
  wind_dir_deg: int | null, wind_speed_kph: float | null
  rain: boolean
  // derived companions (class C): evolution_index (session-best trend),
  // temp_delta_10min, condition_class (DRY|DAMP|WET) — computed views.
}
```

## 10. RaceControlEvent

```ts
RaceControlEvent {
  session_id
  rcm_id: string               // upstream message id when present
  ts: timestamptz
  category: enum               // FLAG | SESSION | CAR_EVENT | PENALTY | INVESTIGATION | OTHER
  type: enum                   // GREEN|YELLOW|DOUBLE_YELLOW|CHEQUERED|CLEAR|
                               // SC_DEPLOYED|SC_ENDS_THIS_LAP|VSC_DEPLOYED|VSC_ENDING|RED_FLAG|
                               // TRACK_LIMITS_NOTICE|LAP_TIME_DELETED|PENALTY|INVESTIGATION|
                               // DR_ENABLED|DR_DISABLED|BLUE_FLAGS|SLIPPIES|...
  scope: { driver_numbers: [int] | null, lap_number: int | null }
  message_raw: text
  parsed_payload: jsonb        // structured fields extracted by normalizer
}
// Derived TrackStatus timeline (GREEN/YELLOW/SC/VSC/RED periods with enter/exit)
// is a materialized projection used by every analyzer.
```

## 11. StrategyEvent *(derived, class C/D)*

```ts
StrategyEvent {
  session_id
  strategy_event_id: uuid
  ts: timestamptz, expires_at: timestamptz | null
  kind: enum                   // PIT_WINDOW_OPEN | UNDERCUT_THREAT | OVERCUT_THREAT |
                               // SC_PIT_OPPORTUNITY | ONE_STOP_FEASIBLE | TWO_STOP_FEASIBLE |
                               // PROJECTED_FINISH_ORDER | TYRE_LIFE_CRITICAL
  subject_driver_ids: [driver_id]
  payload: jsonb               // e.g. { window_laps:[18,24], delta_to_undercut_ms: 1.8 }
  confidence: float | null     // required for class-D content
  model_version: string | null
}
```

## 12. BattleEvent *(derived)*

```ts
BattleEvent {
  session_id
  battle_id: uuid
  driver_a / driver_b: driver_id
  started_ts, ended_ts: timestamptz | null
  start_lap, end_lap: int | null
  peak_closeness_gap_s: float           // min gap during battle
  closing_rate_s_per_lap: float | null  // linear fit of gap series
  drs_range_active: boolean             // ≤1.0s at detection zone
  tyre_advantage: jsonb | null          // {compound delta, age delta}
  sector_advantage: jsonb | null        // which sectors decide it
  outcome: enum | null                  // OVERTAKE_A_OVER_B | DEFENDED | RETIRED | ...
}
```

## 13. AIEvent *(class E wrapper + audit)*

```ts
AIEvent {
  insight_id: uuid
  session_id
  trigger_event_ids: [uuid]        // what caused this
  kind: enum                       // EVENT_EXPLANATION | CHAT_ANSWER | DIGEST | REPORT
  context_pack_ref: uri            // stored pack actually sent (auditability)
  llm_provider/model/version: string
  response_structured: jsonb       // claims[] each with evidence refs into pack
  grounding_check: { passed: boolean, unsupported_claims: [..] }
  latency_ms, token_usage: { prompt, completion }
  created_at
}
// Raw LLM prose is NEVER stored without the pack that produced it.
```

## 14. ReplayFrame *(recording unit)*

```ts
ReplayFrame {
  frame_id: bigserial
  session_id
  seq: bigint                     // strict order
  session_ts: timestamptz         // original session clock (replay clock source)
  wall_ts: timestamptz            // receipt time when recorded live
  channel: enum                   // TIMING|TIMING_APP|CAR_DATA|POSITION|WEATHER|RCM|
                                  // SESSION_INFO|TRACK_STATUS|DRIVER_LIST|LAP_COUNT|TEAM_RADIO|...
  payload_canonical: jsonb        // already-normalized event/document (NOT vendor raw)
  raw_ref: uri | null             // pointer into raw .jsonl.zst archive
}
// Recording = append-only sequence of ReplayFrame for one session.
// ReplayProvider folds frames back through the SAME pipeline (REPLAY_ARCHITECTURE.md).
```

## 15. Cross-cutting rules

1. **Null means unknown** — no sentinel zeros/fake values anywhere.
2. **Mutability policy**: laps/sectors are mutable until session FINISHED then
   frozen; events are append-only; AIEvents immutable with packs retained.
3. **Every derived column stores its `provenance.class` and generator version**
   so models can be re-run/replaced without ambiguity.
4. **Canonical units**: ms (times), km/h (speed), % (throttle/brake/humidity),
   °C (temps), m (distance), kg? N/A (no fuel data exists — class F).
5. Enumerations are closed; unknown upstream values map to explicit
   `*_UNKNOWN` variants + warning log, never silent coercion.
