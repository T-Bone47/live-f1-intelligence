# Phase 12A — Spatial Foundation (design)

Status: design, awaiting review. Date: 2026-09-26. Branch:
`phase-12-spatial-intelligence` (stacked on `phase-11-race-command-center`;
PR #2 is still open).

Phase 12 (Spatial Race Intelligence) is split into four sub-projects, each
with its own spec, plan and implementation:

| sub-project | scope |
|---|---|
| **12A (this spec)** | backend spatial foundation: track reference, measured timing lines, validation gate, per-car spatial state, API, Dutch GP validation |
| 12B | track map in the command center, driven by the Phase 11 cursor (cursor granularity decided there) |
| 12C | telemetry ↔ map synchronization, spatial lap comparison, Evidence Workbench spatial context |
| 12D | battle spatialization, pit-lane geometry from observed traversals, corners only if a licensed source is approved |

12A produces evidence only. It has no UI.

## 1. What 12A answers

"Where on the circuit is each car at session time *t*, how sure is that, and
where are the official timing lines?", on geometry that is derived from the
session's own data, validated against official timing, versioned and
traceable. If the validation fails, spatial output fails closed.

Non-goals for 12A: any frontend, cursor changes, telemetry synchronization,
corners, DRS zones, pit-lane geometry, battles, live hub support, prediction,
AI, and anything RaceWise does.

## 2. Evidence that shaped this design

Measured on the 2026 Dutch GP race recording (OpenF1 11353,
`recordings/dutchgp/openf1-11353-race`) with throwaway scratchpad scripts.
The implementation must reproduce these numbers in real-data tests; they are
not constants.

| finding | measurement |
|---|---|
| location coverage | 890,494 samples, 22 cars, to 15:14Z; z present |
| cars share one line | 75.5% of 115,042 on-track samples lie within 0.5 m of one car's lap polyline |
| timing-line placement, laps next to pit stops excluded | finish median 4.8 m / p95 17.6 / p99 33.8; S1 3.8 / 12.4 / 19.1; S2 4.2 / 14.8 / 24.8 |
| reference independence | three reference laps give dispersions within 0.02 m |
| unit ratio | closed loop 42,129.5 feed units vs cited 4.259 km = 9.89 units/m |
| outliers | #14 lap 37 (243 m at S1, 403 m at S2); #14 at S2 on laps 7/41/45 (67-95 m); #41 lap 5 finish (1,671 m, pit-adjacent) |
| DRS | `drs` is null in all 900,900 car samples |
| corners | no source: FastF1 is not installed; `/circuit` defers MultiViewer "until licensed/verified" |

Consequences:
- The feed carries no racing line. No lateral or line claim is possible.
- A p95 of about 12-18 m supports map, sector and segment-region claims. It
  does not support corner-level metre claims, which is consistent with the
  Phase 10.3 S2 failure.

## 3. Decisions (user-approved, 2026-09-26)

1. **Decomposition:** 12A first; 12B-12D get their own specs.
2. **Gate: claim-scoped.**
   - `MAP_SECTOR` passes when every timing line (finish, S1, S2) has
     p95 ≤ 20 m.
   - `CORNER` passes when every line has p95 ≤ 5 m.
   - Both thresholds are product policy chosen by the user and labelled as
     such, not tuned.
3. **Approach:** geometry is derived per session from its own location feed.
   It reuses the Phase 10.3 `Centerline` and is cached next to the
   recording.

## 4. Architecture

```
recording (frames.jsonl.zst)
  -> spatial/source.py        Lap, PitStop, TelemetryLocationSample for one session
                              (identity-guarded, bucketed by each row's own driver, time-sorted)
  -> spatial/reference.py     deterministic reference lap -> CLOSED Centerline
  -> spatial/timing_lines.py  finish/S1/S2 crossings -> line locations + dispersion
  -> spatial/gate.py          MAP_SECTOR / CORNER results
  -> spatial/samples.py       every sample -> flag, reference fraction, lap, Confidence
  -> spatial/state.py         state of every car at time t (no extrapolation)
  -> spatial/contract.py      track_reference_v1, spatial_state_v1, spatial_trace_v1:
                              pydantic strict, extra=forbid, allow_inf_nan=False; canonical JSON
  -> storage/spatial_store.py cache next to the recording, keyed like timeline_v1
  -> API                      GET /sessions/{sid}/track
                              GET /sessions/{sid}/spatial?at=
                              GET /sessions/{sid}/spatial/{driver}?from=&to=
```

**Reuse, with no second engine.** `track_geometry.Centerline` supplies the
path, projection and arc length. `Confidence`, `confidence_rank` and
`MAX_GAP_S` (2.0 s) come from `lap_distance`. `iter_recording_envelopes`
reads the recording, and `recording_session_id` / `index_recordings` locate
it.

**Engine changes** (additive and backward compatible, each with a test):
- `Centerline.point_at(s)`: distance → (x, y), needed for distance → XY.
- A closed loop is passed as `points + [points[0]]`. The window search
  already wraps modulo the segment count, so no other change is needed. A
  test proves it.

**Units.** Feed coordinates are OpenF1's own frame: an arbitrary origin and
an undocumented unit.
- Metres exist only where a lap length is cited, in a committed
  `backend/app/spatial/circuits.json` that holds `lap_length_m` and its
  `source`. Initially it has one entry: Zandvoort, 4.259 km.
- `distance_m = reference fraction from the measured finish line × cited
  length`. The measured units-per-metre ratio is reported separately, never
  used to derive metres.
- Without a cited length, metres are null and the gate cannot pass.

## 5. Algorithms

### 5.1 Source and identity
- Read only `Lap`, `PitStop`, `TelemetryLocationSample` and the session
  identity rows.
- Every row's `session_id` must equal the requested session, or the build
  fails (`SpatialIdentityError` → HTTP 500, withheld).
- Samples are bucketed by the row's own `driver_number`. Cross-driver mixing
  is impossible by construction and property-tested with a contaminated
  fixture.
- Samples with null x or y are dropped and counted.
- An exact (0, 0, 0) triple is a no-fix placeholder: the first raw location
  row of the recording (12:15Z, before the session) is (0, 0, 0). These
  samples are dropped and counted as `no_fix`, and the real-data test reports
  when they occur.
- The same pass counts `TelemetryCarSample` rows and those with
  `"drs":null`. It uses a byte search, with no parsing, to evidence the DRS
  capability.
- **Duplicates:** if the same driver has the same ts with identical x and y,
  one sample is kept. If the same driver has the same ts with different x or
  y, both are dropped (no guess). Both counts go into provenance.

### 5.2 Reference lap (deterministic)
Eligible laps must meet all of these:
- timed (`duration_s` present) and `lap_number ≥ 2`;
- not a pit-out lap, and not a lap on which or after which the driver
  stopped (pit-adjacent);
- location coverage over the whole lap: the first sample within `MAX_GAP_S`
  of the start, the last within `MAX_GAP_S` of the end, and no internal gap
  over `MAX_GAP_S`.

Choose the fastest eligible lap; ties go to the lower driver number, then
the lower lap number. Its consecutive distinct (x, y) points, closed, form
the reference.

### 5.3 Timing lines (measured, not assumed)
For each eligible lap (the §5.2 rules, without the coverage rule):
- the probe times are lap start (finish line), start + S1 (S1 line), and
  start + S1 + S2 (S2 line);
- the car position at each probe is interpolated linearly in time between
  the bracketing samples of **that** driver, and only if the bracket gap is
  ≤ `MAX_GAP_S`;
- that position is projected onto the reference.

Line location is the circular median of the projections. Dispersion is
|Δ fraction| × cited length. Percentiles are nearest-rank
(`sorted[ceil(q·n) − 1]`). For each line, report:
- n and the exclusion counts by reason (`LAP_1`, `PIT_ADJACENT`,
  `NO_SECTOR_TIME`, `NO_BRACKET`, `GAP`);
- median, p90, p95, p99 and max in metres;
- the five worst crossings (driver, lap, metres).

**Nothing is trimmed.** Outliers stay in the statistics and are listed, and
the validation doc must explain each listed outlier from the data.

**Reference independence.** Rebuild with the 2nd and 3rd eligible reference
laps and compare the line-to-line distances (finish→S1, S1→S2, S2→finish).
Report the maximum difference in metres.

### 5.4 Gate
- `MAP_SECTOR` passes when all three lines have p95 ≤ 20 m, n ≥ 60 per
  line, and a reference-independence difference ≤ 20 m.
  - n ≥ 60 leaves at least three observations above the p95. This is
    labelled PROVISIONAL.
- `CORNER` passes when all three lines have p95 ≤ 5 m, under the same n
  rule.
- Without a cited lap length, both fail with the reason
  `NO_CITED_LAP_LENGTH`.
- Failing `MAP_SECTOR` makes `/spatial` return 409. `/track` still returns
  the validation, with `status: UNVALIDATED` and no geometry.

### 5.5 Sample classification
Each sample is projected with a windowed hint, per driver. Its flag:

| flag | condition |
|---|---|
| `PIT_LANE` | inside a verified pit window (§5.7) |
| `OFF_REFERENCE` | lateral offset > `ON_REFERENCE_TOL` (feed units; garage, red-flag pit lane, off track) |
| `ON_REFERENCE` | otherwise |

- Only `ON_REFERENCE` samples get a reference fraction, lap-relative
  distance and lap number. The others keep x, y with a null fraction.
- **`ON_REFERENCE_TOL` is derived, not chosen**, in feed units. Lateral
  offsets are never converted to metres, because only along-track distance
  has a cited length. It is the p99.9 of lateral offsets of samples inside
  eligible laps. The derivation must show that fewer than 0.1% of
  pit-window samples fall inside it.
  - If the two populations overlap, the tolerance is labelled PROVISIONAL
    and the overlap is reported.
- The 10.3 continuity guards apply per lap:
  - backward jitter within `BACKTRACK_TOL_FRACTION` is held and marked
    MEDIUM;
  - a larger backward jump, or progress faster than `MAX_RATE_FACTOR` × the
    lap mean, is marked NONE (withheld).

### 5.6 State at time t (`spatial_state_v1`)
For every driver in the session, find the bracketing samples of that
driver:

| case | status | output |
|---|---|---|
| t outside the driver's coverage | `NO_COVERAGE` | nulls |
| bracket gap > `MAX_GAP_S` | `STALE` | the last sample ≤ t with `age_s`, confidence LOW, no interpolation |
| both samples `ON_REFERENCE`, same lap-unwrapped | `POSITIONED` | fraction interpolated (unwrapped across the line); (x, y) = `Centerline.point_at(fraction)`; confidence = the worse of the two samples |
| either sample `PIT_LANE` or `OFF_REFERENCE` | `POSITIONED` | (x, y) linear in feed coordinates; fraction null; flag carried |

Every entry carries the bracket (the two sample timestamps and the gap). No
value is ever extrapolated past a driver's last sample. The spatial layer
never infers session state: race phase stays the timeline's job.

### 5.7 Pit windows (verify before relying)
- Window = [`PitStop.ts`, `PitStop.ts + lane_duration_s`].
- The semantics of `PitStop.ts` are **unverified**. Two hypotheses are
  measured:
  - `ENTRY`: window = [ts, ts + lane];
  - `EXIT`: window = [ts − lane, ts].
- For each, implementation measures the share of in-window samples beyond
  `ON_REFERENCE_TOL`. The mode with the higher share is used if it is
  ≥ 90%. Otherwise the pit window is not used and pit lane is detected by
  offset only. This is reported.
- Prior evidence favours `EXIT`. #1's red-flag stop has ts 13:33:05Z and
  lane 1,571.5 s: an EXIT window starts at 13:06:53Z, inside the red flag
  (13:05:28-13:33:00Z). An ENTRY window would run to 13:59Z, past the
  restart. The measurement decides.

### 5.8 Trace (`spatial_trace_v1`)
For one driver over [from, to] (at most 600 s, a resource guard rather than
an analytical tolerance), the classified raw samples in time order. There is
no resampling.

## 6. Contracts (canonical JSON, versioned)

**`track_reference_v1`**
- identity and versions: `contract_version`, `builder_version`, `track_id`
  (`trk1_` + sha256 over the builder version, session, input digest and
  cited length/source, truncated to 24 hex characters), `session`
  (identity as stored);
- `circuit`: short name, `lap_length_m` and `lap_length_source`, or null;
- `coordinate_system`: kind `OPENF1_LOCATION_FEED`, `units: undocumented`,
  `measured_units_per_metre`, `origin: arbitrary`;
- `status`: `VALIDATED_MAP_SECTOR` | `UNVALIDATED`;
- `reference`: driver, lap, started_at, duration_s, point count, loop length
  in feed units, and `polyline` (only when validated);
- `timing_lines[]`: `FINISH | S1 | S2` with fraction, `distance_m`, x, y,
  n, exclusions, dispersion and worst crossings;
- `validation`: per-claim gate results with thresholds, observed values and
  reasons; reference independence; `on_reference_tol_feed_units` with its
  derivation; pit-window hypothesis results;
- `capabilities`, each measured or sourced:
  - `racing_line: false`, with lateral offset percentiles (feed units) of
    eligible-lap samples;
  - `drs_zones: false`, with the car-sample and DRS-null counts;
  - `corners: false` (no source);
  - `pit_lane_geometry: false`;
- `limitations[]`: see §7;
- `provenance`: the chain; `input_digest` (sha256 over the canonical rows
  used); counts for dropped nulls and duplicates.

**`spatial_state_v1`**
- `contract_version`, `builder_version`, `session_id`, `at`, `track_id`;
- `drivers[]`: `driver_number`, `status`, `flag`, `confidence`, `x`, `y`,
  `reference_fraction`, `distance_m`, `lap_number`, `bracket`, `age_s`;
- `limitations[]`.

**`spatial_trace_v1`**
- the same envelope, with one driver's `samples[]`: ts, x, y, flag,
  fraction, `distance_m`, lap, confidence.

The validator rejects:
- unknown fields, NaN/Inf and wrong enums;
- a fraction on a non-`ON_REFERENCE` sample, and metres without a cited
  length;
- a `POSITIONED` status without a bracket, and a `STALE` status without
  `age_s`;
- a mismatched `track_id` or session;
- a polyline on an `UNVALIDATED` reference.

## 7. Limitation codes

| code | meaning |
|---|---|
| `FEED_LINE_NOT_RACING_LINE` | cars are reported on one shared line; there is no lateral or racing-line information |
| `METRES_NORMALIZED_TO_CITED_LENGTH` | metres = fraction × cited lap length, from the measured finish line |
| `UNITS_UNDOCUMENTED` | feed units are undocumented; the ratio is measured |
| `CORNER_PRECISION_NOT_MET` | CORNER gate failed: no corner-level metre claims |
| `CORNERS_UNAVAILABLE` | no licensed or verified corner source |
| `DRS_DATA_ABSENT` | DRS is null in every car sample of the session |
| `PIT_LANE_GEOMETRY_UNAVAILABLE` | pit lane is a flag, not a path |
| `INTERPOLATED_BETWEEN_SAMPLES` | positions at t lie between two real samples (bracket given) |
| `RECORDING_ONLY` | built from recordings; live hubs are not supported in 12A |

## 8. API and errors

| route | success | errors |
|---|---|---|
| `GET /api/v1/sessions/{sid}/track` | `track_reference_v1` (+ `X-Spatial-Contract`) | 404 no recording; 500 withheld (contract or identity) |
| `GET /api/v1/sessions/{sid}/spatial?at=<ISO-8601>` | `spatial_state_v1` | 422 bad or naive `at`; 404 no recording; 409 geometry `UNVALIDATED` (body = validation summary); 500 withheld |
| `GET /api/v1/sessions/{sid}/spatial/{driver}?from=&to=` | `spatial_trace_v1` | 422 bad range / from ≥ to / window > 600 s / driver outside 1-99; 404 no recording or driver not in session; 409; 500 |

- All three share the existing rate limit and session-id validation.
- The legacy `/circuit` stub is unchanged (backward compatibility).
- There is no DB migration.

## 9. Storage and performance

- `<recording>/track_reference_v1.json` + `.key`, and
  `<recording>/spatial_samples_v1.bin` + `.key` (binary columnar, per
  driver: ts, x, y, fraction, flag, lap, confidence).
- Key = `"{builder version}|{frames size}|{frames mtime_ns}"`. A mismatched
  cache is rebuilt, never served.
- Loaded once per process under a lock. State at t is a bisect per driver.
- **Targets to measure and document (not claims):**
  - cold build time;
  - cache load time;
  - `/spatial?at=` median and p95 latency over 1,000 random t;
  - resident memory of the loaded index.

## 10. Failure modes (each tested)

missing recording; recording of another session; contaminated driver rows;
wrong-session rows; null coordinates; duplicate and conflicting samples;
coverage gaps; t before or after coverage; stale bracket; pit lane;
red-flag garage cluster; incomplete lap; missing sector times; no cited lap
length; gate failure; tampered cache key; corrupted cache; contract tamper
(extra field, NaN, fraction on off-reference).

## 11. Testing

- **Unit (synthetic, exact geometry).**
  - closed-loop projection and wrap; `point_at` round trip;
  - line location and zero dispersion on a synthetic track with known speeds
    and timestamps;
  - gate boundaries (20 m and 5 m, `≤` vs `<`, n = 59/60);
  - pit window and off-reference;
  - STALE and NO_COVERAGE;
  - duplicates;
  - deterministic reference choice and tie-break.
- **Property.**
  - positions for driver X are invariant to adding or removing any other
    driver's rows (contamination);
  - the fraction never runs backwards within a lap beyond jitter hold;
  - the state at a real sample's timestamp equals that sample;
  - no output outside coverage.
- **Real data** (skips without the recording):
  - every §2 number reproduced by independent brute-force recomputation (no
    window search), to 1e-6;
  - `MAP_SECTOR` passes and `CORNER` fails;
  - DRS null count; on-line share;
  - listed outliers present;
  - golden `docs/spatial/track_reference_v1_dutch_gp_2026.json` locked
    byte-for-byte (`.gitattributes -text`).
- **API.**
  - every route and error code;
  - route bytes = builder bytes;
  - determinism across repeats.
- **Mutation** (each must be killed):
  - loop not closed; pit window ignored; interpolation across drivers;
  - gate `≤` → `<`; lap 1 not excluded; pit-adjacent not excluded;
  - stale interpolated; fraction not unwrapped at the line;
  - tie-break removed; identity guard removed;
  - fraction on off-reference; metres without a citation;
  - cache key without the builder version; conflicting duplicates kept.

## 12. Deliverables

- Code: `backend/app/spatial/`, `backend/app/storage/spatial_store.py`, the
  API routes, and `backend/app/spatial/circuits.json`.
- `scripts/spatial_report.py` regenerates the golden.
- `docs/PHASE_12_SPATIAL_INTELLIGENCE.md` (12A sections) and
  `docs/PHASE_12_SPATIAL_VALIDATION.md` (measured Dutch GP results, outlier
  explanations, pit-window hypothesis, tolerance derivation).
- A CLAUDE.md handoff update.
- Small logical commits, each green.

## 13. Open items measured during implementation

1. The semantics of `PitStop.ts` (§5.7).
2. The derivation of `ON_REFERENCE_TOL` and its population separation
   (§5.5).
3. The cause of each listed outlier, in particular the #14 S2 offsets
   (location stream gap, clock offset, or pit).
4. When the no-fix (0, 0, 0) placeholders occur (§5.1).

None of these is assumed. Each is reported in the validation doc.
