# Phase 10.4 — Deterministic Time-Loss Attribution

Labels used throughout: **VERIFIED** (checked against real data or the
source's own records), **CALCULATED** (deterministic arithmetic on verified
inputs), **INFERRED** (a temporal association, never a cause),
**UNAVAILABLE** (the inputs do not support it, so the engine does not claim
it).

## 1. Objective

The engine answers "where did A gain or lose time to B, by how much, how
sure is that, and which control inputs differed around it?". Every number
comes from deterministic code, and no LLM is involved. The explanation
layer (10.5) will phrase these facts; it will not measure them.

## 2–4. Relationship to 10.1B, 10.1C and 10.2

```
10.1B lap_distance (distance axis, sync, delta_t)      authoritative, unchanged
   -> 10.1C lap_comparison.compare_driver_laps          authoritative, unchanged
      -> 10.2 delta_analysis.analyze_delta (DeltaSample) authoritative, unchanged
         -> 10.4 attribution.attribute_comparison       NEW layer
```

- No second synchronization and no second delta. Every delta value is a
  10.2 `DeltaSample.delta_t_s`. The test
  `test_every_segment_change_is_exactly_the_10_2_curve_change` asserts
  exact float equality on real data.
- Reused rather than redefined: `SegmentKind` (including `RECOVERING`),
  `TIMING_RESOLUTION_S`, `SIGN_CONVENTION`, `Confidence`,
  `confidence_rank` and the `contextpacks._fact` shape.
- 10.2's fine segmentation (173 segments on the real pair) stays as it is.
  10.4 does not inherit it as the attribution unit (§6).
- Sign convention: `delta_t = elapsed_A − elapsed_B`, where negative means
  A is ahead. `accumulated_change_s = delta_end − delta_start`, where
  positive means A lost time in the segment.

## 5. Attribution model

`AttributionReport`:
- **`segments[]`** (`AttributionSegment`):
  - `region_id`, `kind` (the 10.2 `SegmentKind`);
  - `inherited_gap_s` (delta at the start, not caused here);
  - `accumulated_change_s` (newly accumulated);
  - `uncertainty_s`, `significant`, `status`;
  - `primary_signal` and `supporting_signals`;
  - `onset_order[]` (each entry tagged `TEMPORAL_ASSOCIATION`);
  - evidence blocks: `braking`, `throttle`, `speed`, `gear`, `drs`;
  - `phase_accumulation_a/b`, `confidence` and `provenance`.
- **`accounting`**, **`sectors[]`** and **`uncertainty`** (§14, §17, §18).
- **`alignment_mode`**, **`limitations[]`**, **`calc_version`**
  (`attribution-1.0.0`).

Evidence classes:
- Sample positions, sector times, gear values and DRS codes are OBSERVED.
- Offsets, changes and bands are CALCULATED.
- `onset_order` and the primary/supporting labels are INFERRED
  associations.
- Causes are never stated.

`status` takes one of these values:

| status | meaning |
|---|---|
| `SINGLE_CONTROL_INPUT` | significant, and exactly one control-input family (brake / throttle / gear / drs) differs resolvably |
| `MULTI_SIGNAL` | significant, and several families differ. **No primary is forced.** |
| `SPEED_ONLY` | significant; speed differs beyond misalignment, but no control input is resolvable |
| `INSUFFICIENT_EVIDENCE` | significant, but nothing is resolvable, or telemetry confidence is NONE |
| `NOT_SIGNIFICANT` | the change lies within the uncertainty band |
| `NO_DATA` | no telemetry coverage, so no delta and nothing attributed |

## 6. Segmentation: straight to straight

**Finding that drove the design.** On the real pair, a generic swing
detector over the 10.2 curve found 41 regions. Inside one 78 kph corner it
found −0.186 s followed by +0.186 s. A driver does not gain 0.19 s and hand
it straight back within 200 m; this is misalignment. A distance-axis
misalignment `e` at speed `v` shifts delta by `e/v`: 12 ms/m at 300 kph,
46 ms/m at 78 kph.

**Rule.**
1. Braking zones are formed from both drivers' brake applications, from the
   last off-sample to the first release sample, merged when they overlap.
2. A segment boundary is placed at the peak mean speed between consecutive
   zones, where the alignment error is smallest.
3. The first and last covered grid points are also boundaries.
4. Every corner therefore lies inside one segment; `NO_DATA` spans are
   never bridged.
5. If a driver has no brake channel, the result is one segment per covered
   run, and this is stated in `limitations`.

On the real pair this gives 12 segments instead of 173 (VERIFIED by
`test_segments_are_far_fewer_than_10_2_and_bounded_off_the_brakes`, which
also checks that no boundary falls on a braking sample).

## 7. Braking detection

Detection reads the real samples of each 10.1B trace, never the
interpolated grid, where a 0→100 step would become a fabricated 50.
- Brake on means `brake_pct > 0`. The real feed is binary 0/100 (VERIFIED).
- Each transition is bracketed by two samples: the change happened in
  `(x_before, x_at]`. A state already held at the first sample is
  censored (`x_before=None`).
- Reported fields: onset, peak and release per driver, together with
  offsets, speed at onset, and the before / during / after split of the
  segment's change.

**Resolvable offset.** The two brackets must be separated by more than the
misalignment bound E. At 3.7 Hz and 300 kph the samples are about 22.5 m
apart, so a 20 m onset difference is **not** resolvable from the brake
channel alone. The engine says so rather than claiming it.

Missing brake channel: no braking comparison and no "did not brake" claim.
This is enforced by a property test; the bug was caught by that test during
this phase.

## 8. Throttle detection

- "Full" is per car: within one integer quantum of that trace's own
  maximum. On the real pair #55 **sits at 99** on straights and #63 at 100.
  Both are full (VERIFIED), so a fixed 100 rule would have misclassified
  #55.
- A lift is a run of non-full samples holding **at most one braking zone**.
  - **Bug found on real data:** #63 exits one corner at 89% and brakes
    again before reaching full. The first version treated the two corners
    as one lift, and reported a spurious −131 m throttle-application
    offset. It is fixed by splitting at every further brake onset.
    Regression tests exist on both synthetic and real data.
- Application is the start of the **final** rise: the first sample after
  the last minimum-throttle sample following braking. Full is `None` if the
  next braking comes first.

## 9. Speed analysis

- Mean, minimum and maximum speed difference over the segment grid.
- Minimum speed per driver from the real samples, with its position. It is
  resolvable only if it differs by more than 1 kph: the feed is integer kph
  (VERIFIED).
- Speed at the segment end (carried exit speed).
- Divergence onset: the first grid point where
  `|Δv| > E·|dv/ds| + 1 kph`, meaning the difference is not produced by
  misalignment on a speed gradient.

## 10. Gear / DRS

- Compared for equality only and **never subtracted**. The reported values
  are fraction differing, minimum gear per driver (integers) and the
  distinct raw values.
- A difference run is resolvable only if it is longer than E plus the
  local sample spacing. Otherwise a shift seen one sample later by one
  driver, or misaligned by E, would look like a gear difference.
- DRS codes are compared raw. Their open/closed meaning is **UNAVAILABLE**:
  it is not verified in this repository.

## 11. Phase model

`FULL_THROTTLE | LIFT | BRAKING | TRANSITION | EXIT | UNKNOWN`, per real
sample:
- TRANSITION: brake released, throttle not yet rising.
- EXIT: rising, not yet full.

**APEX is UNAVAILABLE.** No track geometry exists, and the test
`test_phases_follow_the_control_inputs` asserts the phase set never
contains it. `phase_accumulation_a/b` splits a segment's change by each
driver's own phase. It sums exactly to the segment total, but each part
ends at changing speed, so it is less certain than the total (§18).

## 12. Inherited gap

`inherited_gap_s` is the delta at the segment start. `accumulated_change_s`
is only what changed inside the segment. A constant gap carried from an
earlier loss is never counted as new loss: this is a property test across
sampling phases, and a mutation that mixes the two is killed.

## 13. Recovery

When delta falls while A starts the segment behind (`inherited_gap_s > 0`),
the segment is labelled `RECOVERING` (10.2's own vocabulary), not
`GAINING`.

## 14. Accounting

- `actual_change_s`: the delta change over the covered distance.
- `attributed_change_s`: the sum over `SINGLE_CONTROL_INPUT` and
  `MULTI_SIGNAL` segments.
- `unattributed_significant_change_s`: the sum over `SPEED_ONLY` and
  `INSUFFICIENT_EVIDENCE` segments.
- `below_significance_change_s`: the sum over `NOT_SIGNIFICANT` segments.
- `unaccounted_s`: actual − attributed.
- `no_data_spans`.

Invariants, tested on every synthetic scenario and on the real pair:
- The four parts sum exactly to `actual`.
- Every segment's change equals the curve's change.
- Signals are evidence only and carry no time, so multiple signals can
  never double-count.
- Swapping A and B negates every change and keeps every boundary.

## 15. Confidence

The existing `Confidence` (telemetry integrity) is **unchanged in
meaning**: a segment carries the minimum over its grid points. Alignment
precision is a separate, numeric dimension (`uncertainty_s`, the
`significant` flag, `alignment_mode`), not a second confidence grade.

## 16. Provenance

Each segment records:
- session, drivers and laps;
- grid index range;
- real-sample index ranges and timestamp ranges per driver;
- source provider and `calc_version`.

The trace runs: segment → 10.2 `DeltaSample`s → 10.1B trace samples →
OpenF1 rows (identity-guarded) → provider/session/lap. The JSON contains no
wall-clock times, so a re-run is byte-identical (tested).

## 17. Real-data validation (Singapore 2023 Q, session 9161, #55 lap 19 vs #63 lap 16)

Evidence: `docs/evidence/phase_10_4_singapore_attribution.json`,
regenerated by `scripts/attribution_report.py` and locked by
`test_real_output_matches_the_committed_evidence`. Every segment is listed;
none are selected.

**Uncertainty (VERIFIED at the anchors).** The official sector lines sit
4.308 m (S1) and 2.036 m (S2) apart on the two distance axes, so
E = D = 4.308 m.

| seg | metres (normalized) | inherited gap | change | band | status | resolvable control-input / speed evidence |
|---|---|---:|---:|---:|---|---|
| R01 | 0–435 | +0.000 | −0.060 | ±0.161 | NOT_SIGNIFICANT | min speed 137 vs 135 kph |
| R02 | 435–835 | −0.060 | −0.017 | ±0.158 | NOT_SIGNIFICANT | brake onset −29.6 m; lift −29.6 m |
| R03 | 835–1606 | −0.077 | −0.021 | ±0.084 | NOT_SIGNIFICANT | min speed 158 vs 154 kph |
| R04 | 1606–1872 | −0.098 | +0.022 | ±0.114 | NOT_SIGNIFICANT | min gear 4 vs 3 |
| R05 | 1872–2065 | −0.077 | −0.006 | ±0.109 | NOT_SIGNIFICANT | — |
| R06 | 2065–2480 | −0.083 | +0.083 | ±0.129 | NOT_SIGNIFICANT | min speed 133 vs 131 kph |
| R07 | 2480–2668 | +0.000 | +0.068 | ±0.130 | NOT_SIGNIFICANT | min speed 137 vs 146 kph |
| R08 | 2668–2875 | +0.068 | +0.016 | ±0.114 | NOT_SIGNIFICANT | brake release +11.2 m |
| R09 | 2875–3399 | +0.084 | −0.066 | ±0.108 | NOT_SIGNIFICANT | brake onset +31.8 m; full throttle −26.8 m; min gear 2 vs 3; min speed 66 vs 69 kph |
| R10 | 3399–4150 | +0.018 | −0.051 | ±0.064 | NOT_SIGNIFICANT | min speed 90 vs 86 kph |
| R11 | 4150–4555 | −0.033 | −0.009 | ±0.081 | NOT_SIGNIFICANT | full throttle +19.9 m; min gear 4 vs 3; min speed 111 vs 109 kph |
| R12 | 4555–4846 | −0.042 | −0.055 | ±0.074 | NOT_SIGNIFICANT | brake release +27.2 m; throttle application +27.0 m; min speed 210 vs 212 kph |
| R13 | x 0.981–1.000 | — | — | — | NO_DATA | — |

Offset signs are A − B along the lap. For example, R02's −29.6 m means
#55's brake onset came 29.6 m earlier on the lap.

**Result.**
- **No segment's time change exceeds its measured uncertainty.** These two
  laps are 0.072 s apart, and with ±4.3 m alignment the engine cannot
  distinguish corner-level gains. It says so rather than turning a −0.060 s
  curve change into "Sainz gained 0.06 s in R01".
- Accounting: actual −0.0966 s = attributed 0 + unattributed-significant 0
  + below-significance −0.0966 s.

**Control inputs that genuinely differ** (resolvable beyond the brackets
and E; associations, not causes):
- #55 brakes 29.6 m earlier in R02 and 31.8 m later in R09.
- #55 uses **2nd gear in R09 where #63 stays in 3rd**. This was
  independently confirmed from the raw rows: #63 never uses 2nd on this
  lap.
- #63 regains full throttle 26.8 m earlier in R09.

**Sectors (official = VERIFIED, engine = CALCULATED).**

| sector | official A−B | engine | engine − official |
|---|---:|---:|---:|
| 1 | −0.068 | −0.099 | −0.031 |
| 2 | +0.093 | +0.117 | +0.024 |
| 3 | −0.097 | UNAVAILABLE (telemetry ends at x = 0.981) | — |

The official sector deltas sum exactly to the official lap delta of
−0.072 s (tested to 1e-9). The engine's sector errors match the 10.2
audit.

**API lineage (VERIFIED).** The real rows were written to a real Postgres
16, and `/attribution` returned output identical to the engine run
directly (`tests/test_attribution_api.py`).

## 18. Thresholds (significance model)

For a segment from i to j:

`band = E·|1/v_j − 1/v_i| + (D + W)·max(1/v_i, 1/v_j) + 0.001 s`

| term | value | status |
|---|---|---|
| E, misalignment bound | the largest \|misalignment\| at the official S1/S2 lines, **measured per comparison** | VERIFIED at 2 points. Between anchors it is a lower bound, so "significant" means "not explained by the measured misalignment". |
| D, within-segment misalignment change | = E | **PROVISIONAL.** The real anchors move 2.27 m between S1 and S2 (< E). A linear drift rate fitted to the two anchors was **rejected**: on synthetic ground truth it under-predicted a within-segment change about 5×. |
| W, speed-quantization random walk | 3·√(σ_A² + σ_B²), with σ = (0.5/3.6/√3)·√(Σdt²) over the segment's real sample intervals | DERIVED. The integer-kph feed is verified; 3σ is the conventional 99.7% level. On synthetic ground truth this term explained a 1.8 ms delta move through an *identical* corner. |
| 0.001 s | 10.2 `TIMING_RESOLUTION_S` | reused |
| speed/throttle quantum | 1 kph / 1 % | VERIFIED integer on the real feed (tested) |
| E fallback | 4.31 m when a comparison has no sector anchors | **PROVISIONAL.** It comes from the one real pair and is labelled in `limitations`. |

## 19. Limitations

- The distance axis is `NORMALIZED_DISTANCE` (10.1B speed integration);
  metres are *not* physical track positions.
- Phase 10.3 position projection is **not** used (its real S2 check failed).
  If 10.3 traces are passed in, `alignment_mode` reports
  `POSITION_PROJECTED`; nothing is silently upgraded.
- E rests on two anchors per lap, and D = E is provisional. Calibration
  needs more real pairs.
- Intra-segment splits (braking before/during/after, per-phase) end at
  changing speed. Their bands (`band_before_s`, etc.) are reported, and are
  wider than the segment's.
- The mean throttle difference includes per-car calibration (99 vs 100 on
  the real pair); this is flagged in `limitations`.
- Brake is binary on this feed: no pressure modulation or peak-force
  comparison is possible.
- DRS open/closed semantics are unverified; corner names and apex are
  UNAVAILABLE.

## 20. API

`GET /api/v1/sessions/{session_id}/attribution?driver_a&lap_a&driver_b&lap_b&lap_length_m&lap_length_source`

- The route loads stored laps and car telemetry and runs 10.1B → 10.4.
- `lap_length_m` must be supplied **with** its citation: there is no circuit
  geometry, and a length is never invented.
- A lap without a duration is refused (422). No time window is guessed.
- Response: `session_id`, `drivers`, `lap_length`, `alignment` (mode and
  note), `attribution` (the full report) and `context_pack`.

## 21. Performance

Measured with `scripts/bench_attribution.py` (`attribute_comparison` only,
median of 15 runs, Python 3.11):

| case | grid | real samples | time | peak memory |
|---|---:|---:|---:|---:|
| REAL pair, step 0.001 | 1,001 | 681 | ≈10 ms | 183 KiB |
| REAL pair, step 0.0001 | 10,001 | 681 | 54.9 ms | 798 KiB |
| SYNTHETIC 20 km lap, step 0.001 | 1,001 | 2,220 | 23.4 ms | 317 KiB |
| SYNTHETIC 20 km lap, step 0.0001 | 10,001 | 2,220 | 55.2 ms | 939 KiB |

- The cost is O(N log M) in grid points N and samples M: per-segment
  sample access uses bisect ranges, and no quadratic path remains.
- A 10× finer grid costs 5.6× time, sub-linear because of fixed per-sample
  work.

## 22. Phase 10.5 handoff

`attribution_facts(report)` returns `lap_attribution_v1`: 17 facts on the
real pair plus `limitations`. It contains **no raw telemetry**.

- `attr_summary` holds:
  - the official lap delta and the engine delta at the last covered point;
  - `alignment_mode`, the misalignment bound and its source;
  - the sign convention.
- `attr_accounting` holds actual, attributed, unattributed-significant,
  below-significance and unaccounted.
- `attr_sector{1,2,3}` holds the official delta, the engine change and the
  error. Its class is **B** when only official timing exists and **C**
  when an engine value is included.
- `seg_Rnn`, one per data segment, holds:
  - position: `region_id`, x and metre range;
  - time: `direction`, `inherited_gap_s`, `accumulated_change_s`,
    `uncertainty_s`, `significant`;
  - labels: `phase`, `status`, `primary_signal`, `supporting_signals`,
    `onset_order`;
  - evidence: `speed_delta_mean_kph`, `min_speed_difference_kph`, the brake
    onset offset and its resolvability, the throttle application offset and
    its resolvability, and the gear/DRS difference fractions;
  - context: `alignment_mode` and `association: TEMPORAL_ASSOCIATION`.

What 10.5 may say is exactly what these facts support. On this pair that
is "no segment's change exceeds its measured uncertainty", together with
the resolvable control-input differences, stated as associations.

## Tests

| file | kind | tests |
|---|---|---:|
| `test_attribution_signals.py` | synthetic, detector definitions | 13 |
| `test_attribution.py` | synthetic, engine mechanics | 24 |
| `test_attribution_properties.py` | synthetic, invariants over 15 scenario × sampling cases | 85 |
| `test_attribution_real_pair.py` | **real**, cross-checked against the raw rows | 14 |
| `test_attribution_api.py` | **real** rows through **real** Postgres | 2 |

19 mutations were each killed:
- gain/loss sign, inherited gap = end delta, change including the inherited
  gap, and the recovery label;
- brake onset one sample late, throttle application at the minimum, and
  the threshold ignoring the band;
- the W term removed, brackets ignored, gear always resolvable, and gear
  averaged;
- the NO_DATA tail dropped, speed-only counted as attributed, missing brake
  treated as no braking, and a forced primary on multi-signal;
- a fixed 100% full throttle, a lift spanning two corners, modal → max, and
  the sector fact class.
