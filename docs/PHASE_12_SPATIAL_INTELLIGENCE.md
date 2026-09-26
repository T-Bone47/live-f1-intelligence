# Phase 12 — Spatial Race Intelligence

Phase 12 answers "where on the circuit is something happening, and what
measurable vehicle behaviour is occurring there?". It is split into four
sub-projects, each with its own spec, plan and evidence:

| sub-project | scope | status |
|---|---|---|
| **12A** | backend spatial foundation: track reference, measured timing lines, validation gate, per-car spatial state, API | **complete** (this document) |
| 12B | track map in the command center, driven by the Phase 11 cursor | next |
| 12C | telemetry ↔ map synchronization, spatial lap comparison, Evidence Workbench spatial context | planned |
| 12D | battle spatialization, pit-lane geometry from observed traversals; corners only with a licensed source | planned |

Where to find each document:
- Spec: `docs/superpowers/specs/2026-09-26-phase-12a-spatial-foundation-design.md`.
- Plan: `docs/superpowers/plans/2026-09-26-phase-12a-spatial-foundation.md`.
- Measured validation: `docs/PHASE_12_SPATIAL_VALIDATION.md`.

12A produces evidence only. It adds no UI, no prediction, no AI and nothing
RaceWise does.

## 1. What 12A answers

"Where on the circuit is each car at session time *t*, how sure is that, and
where are the official timing lines?" The answer uses geometry derived from
the session's own data, is validated against official timing, versioned and
traceable, and fails closed when validation does not pass.

## 2. Geometry source

The source is the session's own OpenF1 `/location` feed, as recorded. No
external circuit data is used.

Why this source:
- There is no dependency to add.
- It is reproducible offline from the recording.
- It shares its frame with every car in the session.

The alternatives considered:
- **One committed geometry per circuit:** rejected, because frame stability
  across sessions cannot be verified with one recording.
- **MultiViewer through FastF1:** the only source of corner numbers, but
  FastF1 is not installed, the licence is unresolved, and alignment with the
  OpenF1 frame is unproven.

Measured facts that shape what can be claimed:
- **One shared line.** The feed reports every car on essentially one line:
  the lateral p50 is 0.79 feed units. There is no racing line or lateral
  information.
- **No DRS data.** `drs` is null in all 900,900 car samples of the 2026 race.
- **No corner source** in this repository.

## 3. Coordinate system

- **Frame:** OpenF1's feed frame, with an arbitrary origin and an undocumented
  unit. The ratio is measured (9.892 units per cited metre) but never used to
  derive metres.
- **Metres:** they exist only where a lap length is cited, in
  `backend/app/spatial/circuits.json`. Zandvoort is 4.259 km, checked against
  its cited page. `distance_m` is the lap fraction measured from the measured
  finish line, times that cited length.
- **Without a citation:** fractions only, and the gate cannot pass.

## 4. Spatial model (`backend/app/spatial/`)

```
recording -> source.py        identity-guarded laps, pit stops, location samples
          -> reference.py     deterministic reference lap -> closed Centerline
          -> timing_lines.py  finish/S1/S2 measured from official timestamps
          -> gate.py          MAP_SECTOR (p95 <= 20 m) / CORNER (p95 <= 5 m)
          -> samples.py       PIT_LANE / OFF_REFERENCE / ON_REFERENCE per sample
          -> state.py         every car at time t; one driver's trace
          -> contract.py      track_reference_v1, spatial_state_v1, spatial_trace_v1
          -> builder.py       the pipeline + fail-closed documents
storage/spatial_store.py      caches next to the recording (keyed, rebuilt on mismatch)
```

**Reused, never re-implemented:**
- the Phase 10.3 `Centerline` and `project_positions`, including its
  continuity guards;
- `Confidence`, `confidence_rank` and `MAX_GAP_S`;
- the recording reader;
- the timeline's canonical JSON.

**Additive engine changes:**
- `Centerline.point_at` (distance → XY);
- closed-loop use;
- an optional `search_window` (performance only; the edge fallback keeps
  results global, and 10.3 output is bit-identical).

## 5. Alignment

**Reference.** The fastest timed lap from lap 2 on that no pit stop touches
and that has full location coverage. Ties go to the driver number, then the
lap number. Its distinct points form the reference, closed into a loop.

**Timing lines.** Each eligible lap gives three probes: its start (the finish
line), start + S1, and start + S1 + S2.
- The car's position at each probe is interpolated between two real samples
  of that driver, never across a gap over 2 s.
- The position is projected onto the reference.
- A line's position is the circular median of its crossings. How far
  crossings scatter from it is the measured placement error.

**Classification.** Each sample gets one flag:

| flag | condition |
|---|---|
| `PIT_LANE` | inside a verified pit window (Dutch GP: `PitStop.ts` marks pit exit) |
| `OFF_REFERENCE` | beyond the derived tolerance (the p99.9 of eligible-lap lateral offsets) |
| `ON_REFERENCE` | otherwise |

Only on-line samples get a lap fraction. Inside a timed lap the 10.3
continuity guards set their confidence; a jump is withheld, never repaired.

**State at t.** Only the driver's own two samples bracketing t are used:

| case | status | output |
|---|---|---|
| outside the driver's samples | `NO_COVERAGE` | nothing |
| bracket gap over 2 s | `STALE` | the last sample and its age; never interpolated |
| both samples on the reference | `POSITIONED` | the fraction interpolated (unwrapped at the line) and the position placed on the reference |
| otherwise | `POSITIONED` | x/y linear between the two samples, no fraction |

A sample in the short gap that lap rows leave at the line still pairs with
its neighbour, at confidence LOW.

## 6. Confidence

Confidence is the project's existing `Confidence`, measuring data integrity:

| grade | meaning |
|---|---|
| HIGH | a continuity-checked on-line sample, or an observed off-line sample |
| MEDIUM | a small backward jitter held (10.3) |
| LOW | on-line outside a timed lap (no continuity check), and every STALE state |
| NONE | withheld by a continuity guard |

Precision is carried separately, not as a grade: the measured timing-line
dispersion and the claim-scoped gate.

## 7. Provenance

- **Every track document carries:**
  - its chain: rows → canonical models → reference → timing lines → gate →
    classification → builder version;
  - an `input_digest` (sha256 over the canonical rows);
  - drop counts (no-fix, null, duplicates);
  - the reference candidates;
  - a content-derived `track_id`.
- **Every state entry** carries its bracket: the two sample timestamps and
  the gap.

## 8. API

| route | returns | errors |
|---|---|---|
| `GET /api/v1/sessions/{sid}/track` | `track_reference_v1` | 404 no recording · 500 withheld |
| `GET /api/v1/sessions/{sid}/spatial?at=` | `spatial_state_v1` (every car at `at`) | 422 naive or malformed time · 404 · 409 unvalidated (with the gate's reasons) · 500 |
| `GET /api/v1/sessions/{sid}/spatial/{driver}?from=&to=` | `spatial_trace_v1` (window ≤ 600 s) | 422 bad range or driver · 404 no recording or driver · 409 · 500 |

- Responses are canonical bytes with an `X-Spatial-Contract` header.
- Times must carry a UTC offset. A `+hh:mm` offset in a raw URL must be sent
  as `%2B`.
- The legacy `/circuit` route is unchanged.
- There is no DB migration.

## 9. Limitations

| code | meaning |
|---|---|
| `FEED_LINE_NOT_RACING_LINE` | no lateral or racing-line information |
| `METRES_NORMALIZED_TO_CITED_LENGTH` | metres are normalized to the cited lap length |
| `UNITS_UNDOCUMENTED` | feed units are undocumented |
| `CORNER_PRECISION_NOT_MET` | on the Dutch GP: no corner-level metre claims |
| `CORNERS_UNAVAILABLE` | no corner source |
| `DRS_DATA_ABSENT` | DRS is null in every car sample |
| `PIT_LANE_GEOMETRY_UNAVAILABLE` | pit lane is a flag, not a path |
| `INTERPOLATED_BETWEEN_SAMPLES` | positions at t lie between two real samples |
| `RECORDING_ONLY` | a running live session is not spatialized |

Also:
- **Tolerance.** The on-reference tolerance is PROVISIONAL: 4.43% of
  pit-window samples lie on the line, where pit roads meet the track.
- **Restart lap.** 10,742 on-line samples are withheld on the red-flag
  restart lap. The 10.3 rate guard is relative to that lap's very slow mean
  pace.
- **Per-car bias.** #14 runs −10.9 m behind at S2. Open findings (the lap-4
  restart crossings) are listed in the validation doc.
- **One session validated.** Other circuits need a cited lap length before
  they can pass the gate.

## 10. Failure modes (each tested)

The synthetic suite covers:
- inputs: a missing recording; a recording of another session;
  contaminated driver rows; wrong-session rows; null and `(0, 0, 0)`
  coordinates; identical and conflicting duplicates;
- coverage: coverage gaps; t before or after coverage; a stale bracket;
  a retired car;
- positions: pit lane; the garage off the line; a gap between lap rows;
  an incomplete lap; missing sector times;
- validation: no cited length; no eligible reference lap; gate failure;
- caches and contracts: a stale, truncated or invalid cache; concurrent first
  requests; ten contract tamper cases.

## 11. Testing

| file | tests | covers |
|---|---:|---|
| `test_track_geometry.py` (+5) | 21 | `point_at`, closed loop, narrow window = global search |
| `test_spatial_source.py` | 7 | identity, bucketing, drops, duplicates, DRS counts, digest |
| `test_spatial_reference.py` | 5 | eligibility, coverage, tie-break, closed reference |
| `test_spatial_timing_lines.py` | 7 | percentiles, circular median, exclusions, worst, independence |
| `test_spatial_gate.py` | 8 | citation, 20/5 m boundaries, n = 59/60, missing lines, independence |
| `test_spatial_samples.py` | 8 | tolerance, ENTRY/EXIT/NONE pit modes, flags, continuity |
| `test_spatial_state.py` | 9 | bracket, unwrap, STALE, NO_COVERAGE, contamination, trace, lap-row gap |
| `test_spatial_contract.py` | 17 | determinism, ids, unvalidated paths, capabilities, 10 tamper cases |
| `test_spatial_store.py` | 9 | caches, key format, corruption, round trip, identity, concurrency |
| `test_spatial_api.py` | 9 | three routes, UTC handling, limits, 404/409/422, determinism |
| `test_spatial_real.py` | 10 | the Dutch GP, independently recomputed (skips without the recording) |

The mutation results are in `PHASE_12_SPATIAL_VALIDATION.md` §10.

## 12. Performance

Measured by `scripts/bench_spatial.py` on the real recording (validation doc §10): cold build 85.8 s once per recording and builder version, warm cache load 0.04 s, index 29.0 MB (tracemalloc peak 89.1 MB on load), and `spatial_state_v1` median 0.40 ms / p95 0.66 ms per request (1,000 random times, document + validation + bytes).

## 13. RaceWise boundary

12A measures and places; it never reasons.
- It does not implement a chatbot, LLM reasoning, causal language,
  prediction, recommendations or autonomous investigation.
- It never uses "better line", confidence-as-psychology, or corner names.

RaceWise may consume `track_reference_v1` and `spatial_state_v1` later, as
evidence.
