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
