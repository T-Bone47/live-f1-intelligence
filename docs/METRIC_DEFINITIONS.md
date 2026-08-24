# METRIC_DEFINITIONS.md

Normative definitions for every Phase-2 metric. Each entry: definition,
formula, inputs, exclusions, edge cases, provenance, limitations.
All outputs are DERIVED (calc_version `analysis-2.0.0`) — never official F1 data.

---

## Lap classification (laps.py)

| Class/Flag | Rule |
|---|---|
| DELETED | tombstone present in correction ledger for (driver, lap) |
| PIT_OUT | upstream `is_pit_out_lap` true |
| PIT_IN | next lap begins a different stint (lookahead) or explicit in-lap flag. LIMITATION: lookahead unknown while streaming → pit-in often classified late/never in live; documented. |
| YELLOW / DOUBLE_YELLOW / SAFETY_CAR / VSC / RED_FLAG | interference period overlaps [lap_start, lap_start+duration) using the ordered RC timeline |
| OUTLIER | duration > 1.07 × driver's median clean sample in the same stint bucket (needs ≥3 samples); SC/VSC/yellow/red laps skip outlier check |
| INACCURATE | upstream accuracy flag false (FastF1) |

Class resolution order: INVALID (deleted/red) > OUTLIER > PIT_IN > PIT_OUT >
FLYING(affected) > REPRESENTATIVE (clean flying lap). Raw rows are never
altered; classification is attached metadata only.

## Timing (timing.py)

- **personal_best**: fastest non-deleted lap duration per driver.
- **session_best/fastest_lap**: min over drivers; `FASTEST_LAP_CHANGE` fires
  only when a previous holder existed.
- **position / previous_position**: from authoritative position events;
  fallback ordering = numeric gap asc, then symbolic/unknown last by number.
- **gap_to_leader**: numeric when float; symbolic strings (`+1 LAP`) stored
  verbatim and EXCLUDED from all numeric series. Never converted.
- **interval**: gap to car directly ahead (same rules).

## Sectors (sectors.py)

- **PB sector i**: driver's fastest valid time. Valid = not deleted at fold
  time (tombstoned laps never enter the books).
- **Session best / PURPLE**: min across drivers for sector i. First sighting
  of a session becomes its holder and classifies PURPLE (broadcast-style).
- **GREEN** = improved own PB without taking session best.
- **YELLOW** = slower than own PB.
- **delta_to_pb** = t − prior_PB (negative = improvement).
- Marshal sectors / mini-segments: DIFFERENT concept (Phase-1 finding);
  segment codes stay verbatim on SectorTime rows, never mixed into these
  numbers.

## Theoretical lap

    theoretical_lap(d) = PB_S1(d) + PB_S2(d) + PB_S3(d)

None unless ALL three exist. `theoretical_improvement` = actual_best −
theoretical. `best_possible_lap` = min over drivers with complete sets.

## Pace (pace.py, PACE_METHODOLOGY.md)

Eligibility: REPRESENTATIVE laps only. Exclusion reasons recorded:
PIT_OUT/PIT_IN/DELETED/YELLOW/DOUBLE_YELLOW/SAFETY_CAR/VSC/RED_FLAG/OUTLIER/
INACCURATE/NO_TIME.

- rolling_pace(N): mean of last N eligible laps (N∈{3,5,10}); None if fewer.
- stint_average: mean eligible laps within one stint window.
- median_pace; field_median: median of per-driver medians.
- pace_trend: OLS slope over trailing 5 eligible laps [s/lap];
  negative = improving. Events: |slope| ≥ 0.3 s/lap → PACE_CHANGE(<0) /
  PACE_DROP(>0), keyed with lap//3 buckets.

## Clean-air v1

```
FALSE : gap_ahead <= 1.0 s OR gap_behind <= 1.0 s
TRUE  : leader? behind>2.0 : (ahead>2.0 AND behind>2.0)
UNKNOWN otherwise/no-data
```
Approximation by design (no DRS-zone data via OpenF1); computed only where
gaps exist.

## Tyres (tyres.py, TYRE_DEGRADATION.md)

- stint windows from records; laps assigned retroactively from ledger.
- degradation fit on (age, duration): MAD-filter (2.5) then OLS;
  MIN_SAMPLES=4; confidence HIGH(n≥8,r²≥0.5)/MEDIUM(n≥5)/LOW else/NONE.
- Output labeled ESTIMATED DEGRADATION with n, r², excluded count.

## Gaps (gaps.py)

- Pair sampling: B's interval to A sampled per event; closing_rate over last W
  (default 3) samples: (last−first)/(n−1) s per sample (~s/lap cadence).
  Symbolic pairs excluded from rates.
- Trend labels: ≤−0.15 CLOSING_FAST; <−0.05 CLOSING; >0.15 OPENING_FAST;
  >0.05 OPENING; else STABLE.

## Battles (battles.py, BATTLE_DETECTION.md)

Thresholds: APPROACH 2.0 / DRS 1.0 / ACTIVE 0.6 / SEPARATE 2.5 / RESET 3.0 s;
confirm ACTIVE needs 2 consecutive close samples; RESET needs 3 samples >
3.0 s. OVERTAKE on authoritative position swap inside an active pair. Pit/ret
immediately ends battle. No probability model.

## Strategy primitives (strategy.py)

- pit_loss_estimate: median observed lane_duration of completed stops
  (<300 s filter excludes red-flag parkings); None until ≥2 stops observed.
- compound baseline lives (ASSUMPTION, configurable): SOFT 15 / MEDIUM 25 /
  HARD 35; window opens at age ≥ base−3 → [age, age+6].
- undercut_indicator: gap_to_ahead ≤ 2.5 s AND attacker_age+4 ≤ defender_age.
- overcut_indicator: gap_to_ahead ≤ 1.8 s AND ahead_in_pit.
- expected_rejoin_position: count(gap_to_leader < mine + pit_loss) + symbolic
  count + 1. All outputs are optimizer INPUTS, not recommendations.

## Weather (weather.py)

Trailing-window (10 samples ≈ 10 min) OLS slope per channel. Threshold
events: |Δ/10 samples| ≥ 1.0 °C (air/track temp) or ≥ 5.0 units (humidity,
wind); rainfall flip → RAIN_START/RAIN_STOP. No impact inference this phase.

## Race control & session

Phase set and timeline semantics: see ANALYSIS/race_control module docstring;
meaningfulness matrix in `session.py` (e.g., pit_windows meaningful only for
SPRINT/RACE profiles).
