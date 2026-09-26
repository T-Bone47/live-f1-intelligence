# Phase 12A — Spatial validation on the 2026 Dutch GP

Every number here was measured on the real race recording (OpenF1 session
11353, `recordings/dutchgp/openf1-11353-race`). All of them are reproduced by
`scripts/spatial_report.py` and locked by `backend/tests/test_spatial_real.py`
(10 tests; they skip without the recording). Nothing was tuned to make a
check pass.

Reproduce:

```powershell
cd backend
.\.venv\Scripts\python.exe ..\scripts\spatial_report.py            # the report
.\.venv\Scripts\python.exe ..\scripts\spatial_report.py --write-golden
.\.venv\Scripts\python.exe -m pytest tests\test_spatial_real.py -v
```

Golden: `docs/spatial/track_reference_v1_dutch_gp_2026.json` (11,519 bytes,
`track_id trk1_5c46f956e6753d06f8583341`, status `VALIDATED_MAP_SECTOR`).

## 1. Source and method

- **Geometry source:** the session's own OpenF1 `/location` feed, as recorded.
  No external circuit data is used.
- **Coordinate system:** OpenF1's feed frame, with an arbitrary origin and an
  undocumented unit.
- **Reference line:** one real lap, chosen by a fixed rule and closed into a
  loop. The rule picks the fastest timed lap from lap 2 on that no pit stop
  touches and that has full location coverage; ties go to the driver number,
  then the lap number.
- **Metres:** a lap fraction measured from the measured finish line, times
  the cited lap length of 4.259 km (Wikipedia, "Circuit Zandvoort", Grand Prix
  circuit 2020-present, accessed 2026-09-26).
- **Validation:** every eligible lap gives three official timestamps: lap
  start, start + S1, and start + S1 + S2.
  - The car's position at each timestamp comes from its own two bracketing
    samples and is projected onto the reference.
  - How far those projections scatter along the track is the measured error
    of placing a timed event on this geometry.

## 2. Inputs

| quantity | value |
|---|---:|
| location rows | 890,494 |
| kept samples | 806,711 |
| `(0, 0, 0)` no-fix placeholders | 83,783 |
| null x/y, duplicate samples | 0, 0 |
| drivers | 22 |
| car samples / with `drs` null | 900,900 / 900,900 |
| duplicate lap rows (later row kept) | 7 |

When the no-fix placeholders occur:

| window | samples |
|---|---:|
| before the first lap start (13:03:28.567Z) | 33,881 |
| after the last lap end (15:09:23.809Z) | 2,080 |
| between those times | 47,822 |

Between those times, almost all placeholders come from cars that had stopped
running:
- #3: 26,663 (its last lap row is lap 1);
- #87: 20,692 (its last lap row is lap 3);
- #14: 467 (a running car).

## 3. Reference and units

- **Reference lap:** #16, lap 60, 74.23 s. It has 275 points and a loop of
  42,129.5 feed units.
- **Measured ratio:** 9.892 feed units per cited metre. This is consistent
  with decimetres to within 1.1%, but the unit is undocumented. The ratio is
  reported only; it is never used to derive metres.
- **Candidates:** #16 L60, #81 L61, #1 L49.
- **Reference independence:** across the three candidates, the distances
  between lines differ by at most **1.087 m**.

## 4. Timing lines and the gate

Dispersion is in metres, using nearest-rank percentiles.

| line | n | position | median | p90 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| FINISH | 1,211 | 0.0 m | 4.76 | 13.55 | **17.74** | 33.75 | 61.38 |
| S1 | 1,197 | 1,484.9 m | 3.81 | 10.20 | **12.60** | 19.68 | 242.61 |
| S2 | 1,189 | 2,939.2 m | 4.19 | 11.74 | **14.89** | 25.57 | 402.65 |

Excluded crossings:
- lap 1: 22 per line;
- pit-adjacent: 130 per line;
- untimed: 5 per line;
- missing sector time: 15 (S1) and 22 (S2);
- coverage gap: 1 each at FINISH and S2.

Gate results (user policy, 2026-09-26):

| claim | threshold | result |
|---|---:|---|
| MAP_SECTOR | p95 ≤ 20 m | **PASS** |
| CORNER | p95 ≤ 5 m | **FAIL** at all three lines, so no corner-level metre claims |

An independent recomputation matches the builder to within 1e-6 m for every
percentile and for both line positions. It uses a brute-force projection onto
the published polyline, with its own interpolation, median and nearest-rank
code, and no `Centerline` or window search.

## 5. Sample classification

**On-reference tolerance: 9.960 feed units.** This is the p99.9 of lateral
offsets over 367,396 samples in eligible laps.

| percentile | lateral offset (feed units) |
|---|---:|
| p50 | 0.786 |
| p90 | 3.856 |
| p99 | 8.196 |
| p99.9 | 9.960 |

Cars are reported on essentially one line, so the feed carries no
racing-line information.

The tolerance is **PROVISIONAL**. 4.43% of pit-window samples fall inside
it, against a 0.1% ceiling. This is expected, because pit entry and exit
roads join the track: a car at the start or end of its pit window is still
next to the racing line.

**Pit windows: `PitStop.ts` marks pit exit (verified).**

| hypothesis | window | samples | share off the line |
|---|---|---:|---:|
| EXIT | [ts − lane, ts] | 128,995 | **95.57%** |
| ENTRY | [ts, ts + lane] | 123,142 | 2.79% |

**Sample flags**

| flag | samples |
|---|---:|
| ON_REFERENCE | 631,964 |
| PIT_LANE | 128,995 |
| OFF_REFERENCE | 45,752 |

**Withheld samples.** 12,494 on-line samples have confidence NONE (fraction
withheld). **10,742 (86%) of them are on lap 3**, the lap that contains the
red-flag restart.
- The Phase 10.3 rate guard is relative to the lap's own mean pace, which the
  restart procedure makes very slow.
- Racing samples on that lap therefore look "too fast" and are withheld. This
  is conservative and is left unchanged.

## 6. Outliers, explained from the data

**Per-car bias: #14 runs behind the line on every line.**

| driver | S1 | S2 | FINISH | laps |
|---|---:|---:|---:|---:|
| #14 | −3.0 m | −10.9 m | −5.7 m | about 65 |

Values are the signed median offset. Every other driver's median is within
±3.0 m at every line (the next largest is #1 at +3.0 m, at S2). #14's
location samples trail its official timing, which explains its S2 tail.

**#14 lap 37: S1 243 m, S2 403 m off.**
- Its sector times are ordinary (27.018 s and 28.012 s).
- Its finish crossing that lap is normal.
- Its lap rows are continuous (+0.054 s).

Nothing in the timing rows explains it. This is a location anomaly local to
that lap, and #14 also has 467 mid-race no-fix samples.

**Lap-row discontinuity.** Across 1,343 consecutive lap pairs, the gap
between one lap's end and the next lap's start has a median of 0.052 s and a
p95 of 0.168 s.

| lap | gap before the lap starts | offset |
|---|---:|---|
| #11 lap 67 | 0.719 s | FINISH 61.4 m, S1 62.7 m (the whole lap is shifted) |
| #11 lap 61 | 0.252 s | S1 26.4 m |

**Open: the restart laps after the red flag.**
- #44, #14 and #16 on lap 4 are 34.8–35.5 m off at FINISH. Those laps last
  160–200 s, and their lap rows are continuous (≤ 0.06 s).
- #27 lap 44 (39.5 m at FINISH, 37.8 m at S1) follows an untimed lap, so its
  continuity cannot be checked.

These are recorded as open findings, not explained away.

## 7. Cross-check with the Phase 11 timeline

Each of the 72 `LAP k` frames is the moment a car completes lap k by official
timing. At that moment, 12A should place that car on the finish line.

**67 frames have a current position on the reference.**
- 66 of them (98.5%) are within the FINISH p95 (17.74 m).
- The worst is 33.2 m, well within the FINISH maximum of 61.38 m. It is lap 4,
  one of the restart outliers.

**5 frames have no current position**, each with an explicit reason:
- lap 2: PIT_LANE (the red flag: the leader crossed the line in the pit lane);
- lap 3: a withheld sample on the restart lap;
- lap 21 and lap 47: PIT_LANE (pit stops ending at the line);
- lap 43: STALE (a gap of more than 2 s in #1's location feed).

The frame's P1 row is not always the car completing the lap. At lap 44 they
differ, because positions can lag (Phase 11 `LATEST_SAMPLE_AT_FRAME`). The
cross-check therefore uses the car completing the lap.

**A defect this cross-check found (fixed test-first).**
- A sample that falls in the ~0.05-0.2 s gap between two lap rows belongs to
  no timed lap. In `state_at`, that dropped the fraction of a car that was on
  the line: #12, lap 6 to 7, 10.8 m before the finish line.
- Such a sample now pairs with its neighbour at confidence LOW, keeping its
  lap from the known side.

## 8. Window search

The reference uses a narrow projection window (8 segments either side) for
speed. On 20 runs of 250 consecutive real samples, it gives the same
projection as a full search, bit for bit (`test_real_narrow_window_...`).

## 9. Cost of one build (report run, this machine)

| step | time |
|---|---:|
| load the recording | 32.9 s |
| build (reference, lines, independence, tolerance, pit windows, classification) | 57.0 s |

Both run once per recording and are cached next to it. The measurements from
`scripts/bench_spatial.py` are in §10.

## 10. Mutation testing and performance

**Mutation sweep.** Each mutant was applied alone, the synthetic spatial
suite was run with `-x`, and the original bytes were restored. The final
result is **19 of 19 killed**.

| # | mutation | killed by |
|---|---|---|
| M1 | reference not closed | `test_a_sample_in_the_gap_between_two_lap_rows_still_gets_a_fraction` |
| M2 | pit windows ignored | `test_pit_lane_samples_keep_xy_but_get_no_fraction` |
| M3 | all samples in the first driver's bucket | `test_rows_are_bucketed_by_their_own_driver_and_time_sorted` |
| M4 | gate `>` → `>=` | `test_map_sector_passes_at_exactly_20_m_and_fails_just_above` |
| M5 | lap 1 not excluded | `test_exclusions_are_counted_by_reason` |
| M6 | pit-adjacent not excluded | `test_exclusions_are_counted_by_reason` |
| M7 | STALE interpolates | `test_gap_over_2_s_is_stale_with_age_and_never_interpolated` |
| M8 | no unwrap at the line | `test_interpolation_unwraps_across_the_finish_line` |
| M9 | tie-break reversed | `test_fastest_eligible_lap_wins_and_ties_break_by_driver_then_lap` |
| M10 | identity guard removed | `test_a_row_from_another_session_fails_closed` |
| M11 | off-line samples get a fraction | `test_off_reference_garage_samples_get_no_fraction` |
| M12 | uncited circuit falls back to 4259 m | `test_unvalidated_session_has_no_polyline_and_no_index` |
| M13 | cache key without builder version | `test_the_cache_key_names_the_builder_version_and_the_recording` (see below) |
| M14 | conflicting duplicates keep the first | `test_identical_duplicates_keep_one_and_conflicting_duplicates_drop_all` |
| M15 | closed loop clamps instead of wrapping | `test_point_at_wraps_on_a_closed_loop_and_clamps_on_an_open_path` |
| M16 | lap-row-gap samples lose the fraction | `test_a_sample_in_the_gap_between_two_lap_rows_still_gets_a_fraction` |
| M17 | polyline allowed on unvalidated geometry | `test_tampered_documents_are_rejected[_t_unvalidated_polyline]` |
| M18 | pit mode ignores the 90% threshold | `test_pit_mode_is_none_when_neither_window_is_off_reference` |
| M19 | tolerance quantile p99.9 → p50 | `test_tolerance_is_the_p999_of_green_lap_offsets` |

**M13 survived the first sweep.** The cache validation already recomputes
the `track_id`, which binds the builder version, so a stale cache was still
rebuilt. The spec (§9) fixes the key format regardless, so a test now pins
it, and M13 is killed.

**Performance** (`scripts/bench_spatial.py`, real recording, this machine):

| measure | result |
|---|---:|
| cold build (load 31.0 s + build 54.7 s + write) | 85.8 s |
| index on disk | 29.0 MB |
| warm cache load (fresh store, caches on disk) | 0.04 s |
| `read_index` tracemalloc peak | 89.1 MB |
| `spatial_state_v1` (document + validation + canonical bytes), 1,000 seeded-random times | median 0.40 ms, p95 0.66 ms, max 1.28 ms |

The cold build runs once per recording and builder version. Before
`search_window` it was projected at about 0.4 ms per sample, which would have
been about 15 minutes. Profiling showed about 83 segment evaluations per
projection, which the narrow window removes.

## 11. Final whole-branch review

A fresh reviewer, which had not seen the implementation, reviewed the whole
branch (`de8d46a..8e7b331`). It found no Critical issues. Four findings were
fixed test-first in one pass (`40d2543`):

| finding | fix | regression |
|---|---|---|
| **The cache key ignored the cited lap lengths.** A corrected or added citation was answered from the old cache, with self-consistent wrong metres. | The key includes a digest of the circuit table in effect. | `test_a_changed_citation_rebuilds_the_cache` |
| **A timing lap was paired with a geometric fraction from the other side of the line.** #1 at 14:05:45.79Z read "lap 25, 4,256.86 m" just after starting lap 25. About 4k samples were affected. | A lap is kept only when the continuity-unwrapped position lies in [0, 1) of that lap from the measured line; otherwise it is withheld and the fraction stays. | `test_timing_lap_and_geometry_that_disagree_at_the_line_withhold_the_lap`, `test_real_lap_numbers_agree_with_the_geometry` |
| **State and trace documents had metres but no precision.** | `line_placement_p95_m`, plus `CORNER_PRECISION_NOT_MET` when the corner gate failed. | `test_state_and_trace_docs_state_their_precision`, `test_real_state_docs_validate_and_state_their_precision` |
| **Unvalidated geometry still published timing-line positions.** The reviewer graded this Minor; it was raised to Important because spec §5.4 says no geometry. | Positions are null when unvalidated; the contract enforces this both ways. | `test_unvalidated_session_has_no_polyline_and_no_index`, tamper `_t_unvalidated_line_position` |

After the fix pass:
- **Backend:** 895 passed, 23 skipped (18 need Postgres, which was down, plus
  the known 5), 1 failed (the known 10.3 S2 check).
- **Real Dutch GP suite:** 12 passed, golden byte-identical.
- **ruff:** clean on every changed file.

**Deferred (minor, not fixed):**
- One store lock covers every session, and failed builds are not memoized.
- Extreme-year `at` values raise `OverflowError`, which surfaces as 500
  instead of 422.
- STALE lifts a NONE sample's confidence to LOW.
- Validator gaps: a unit "m" without a citation, a ratio without a citation,
  and a lap on off-line entries are not rejected.
- The narrow-window comment overstates correctness on non-convex tracks. The
  real spot check is bit-identical.
- No property test that "the fraction never runs backwards"; the §2
  "on-line share" is not reproduced.
- The benchmark omits `index_recordings` and the double store call per
  request.
- `circuits.json` has no layout or year validity.
- A second placeholder point (−3450, −4945), shared by #11 and #14 before
  the race.
- CLAUDE.md numbering.
