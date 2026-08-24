# SNAPSHOT_PROTOCOL.md

The SessionSnapshot is the authoritative live projection. Wire format
f1intel-snapshot-1; full frames carry data, delta frames carry
changes+removed with dotted paths.

## 1. Snapshot schema (fields present ONLY when available)

session:      session_id, session_type, phase, track_flag, current_lap,
              profile, calc_version
leaderboard[] position, driver_number, lap_number, last_lap_s,
              personal_best_s, gap_to_leader_raw (verbatim +1 LAP),
              gap_to_leader_s, interval_s, compound, tyre_age, stint_number,
              rolling5_s, pace_trend_s_per_lap, clean_air, in_pit, retired
fastest_lap   driver, duration_s, at_lap
sector_leaders {S1/S2/S3: time_s + holder}
active_battles[] ahead, behind, state, min_gap_s, last_gap_s, started_lap
weather       air_temp_c, track_temp_c, humidity_pct, wind_speed, rainfall
recent_events last 25 IntelligenceEvents (full provenance)

## 2. Diff format

Deltas contain only changed leaf paths:
    changes: {leaderboard.1.position: 2, fastest_lap.duration_s: 74.23}
Lists are atomic (whole-list replacement); dicts recurse by dotted path.
removed[] lists paths present before and absent now.
Empty cycle publishes nothing; clients rely on seq heartbeat.

## 3. Sequence contract

One monotonic integer per session across ALL frame kinds. Clients detect:
missing sequence (gap) -> resume request; duplicate/lower -> stale -> ignore;
snapshot kind -> replace state wholesale.

## 4. Versioning

Every frame embeds schema=f1intel-snapshot-1 and snapshots embed calc_version
(analysis-X.Y.Z). Additive evolution stays in v1; breaking shape changes bump
the schema string and are advertised on connect.
