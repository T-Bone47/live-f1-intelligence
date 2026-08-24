# EVENT_DEFINITIONS.md

Catalog of deterministic intelligence events (Phase 2). Every event carries:
`event_key` (dedupe identity), `event_type`, `session_id`, `timestamp`,
optional `drivers[]`, `severity`, `metrics`, `evidence`, DERIVED provenance
(calc_version, confidence), and `prediction` flag (true ONLY for forward-
looking estimates).

Severity scale: INFO < NOTABLE < IMPORTANT < CRITICAL.

---

## Identity keys (dedupe contract)

| event_type | key identity | recurrence |
|---|---|---|
| PURPLE_SECTOR | driver\|S{i}\|L{lap} | once per occurrence |
| PERSONAL_BEST (sector) | SECTOR\|driver\|S{i}\|L{lap} | once |
| PERSONAL_BEST_LAP | driver\|L{lap} | once |
| FASTEST_LAP_CHANGE | L{lap} | once per change (first holder suppressed) |
| POSITION_CHANGE | driver\|L{lap}\|{old}->{new} | once per transition |
| PACE_CHANGE / PACE_DROP | driver\|W5\|BUCKET{lap//3} | ≤1 per ~3 laps/driver/direction |
| TYRE_DEGRADATION_CHANGE | driver\|STINT{n}\|SIGN{PLUS/MINUS} | once per sign per stint |
| BATTLE_STARTED | {ahead}v{behind}\|L{lap} | once per battle start |
| BATTLE_ESCALATED | pair\|TO_{STATE} | once per state entry |
| BATTLE_SEPARATED | pair\|SEP\|L{start} | once |
| OVERTAKE | {winner}v{loser}\|L{lap} | once |
| PIT_STOP | driver\|TS{epoch} | once per stop |
| PIT_WINDOW | driver\|FROM{open_lap} | once per window (prediction) |
| WEATHER_CHANGE | METRIC\|DIR\|BUCKET{idx//10} | throttled by bucket |
| RAIN_START/STOP (via WEATHER_CHANGE) | metric=RAIN\|FLAG\|bucket | per flip |
| SAFETY_CAR / VSC / RED_FLAG | RCM{rcm_key} | once per upstream message |
| SESSION_STATE_CHANGE | {from}_{to}\|N{seq} | once per transition |

Bucketing guarantees no polling spam while allowing legitimate recurrence.
The deduper holds 50k keys (LRU); eviction beyond that re-permits a key —
accepted, documented behavior.

## Severity assignments

| Event | Default severity |
|---|---|
| RED_FLAG | CRITICAL |
| FASTEST_LAP_CHANGE, OVERTAKE, SAFETY_CAR, VSC, SESSION_STATE_CHANGE, degradation \|rate\|≥0.25 s/lap | IMPORTANT |
| PURPLE_SECTOR, POSITION_CHANGE (top-10 involvement), BATTLE_*, PIT_STOP, PACE events (\|slope\|<1.0), weather shifts | NOTABLE |
| PERSONAL_BEST*, PIT_WINDOW, minor pace shifts, non-top-10 position swaps | INFO |

## Payload metrics (highlights)

- PURPLE_SECTOR: sector, time_s
- POSITION_CHANGE: from, to, lap
- PACE_*: slope_s_per_lap, window
- TYRE_DEGRADATION_CHANGE: estimated_degradation_s_per_lap, r_squared,
  samples, confidence, label="ESTIMATED DEGRADATION - not official data"
- OVERTAKE: state + pair context
- PIT_STOP: lane_duration_s
- PIT_WINDOW: window_laps[2], compound, tyre_age
- WEATHER_CHANGE: direction, delta_per_10_samples, current / rainfall flag
- SESSION_STATE_CHANGE: from, to

## Provenance

Every event embeds `DerivedProvenance.as_dict()`:
`kind:"DERIVED"`, session_id, calculated_at (UTC ISO), calc_version, optional
source_provider, input_event_ids (where practical), confidence. Events with
`prediction:true` are estimates about the future — never observed facts.
