# Phase 12C Spatial Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show where on the track time was gained or lost, and what the car
was doing at the one cursor, from recorded data only.

**Architecture:**
- **Backend.** A recording store serves laps and car telemetry through the
  same canonical models, so the unchanged evidence and telemetry engines
  run without Postgres.
- **Placement.** `evidence_spatial_v1` places evidence segments on the 12A
  track by each driver's own sample timestamps.
- **Frontend.** The command center gains a car-telemetry panel (samples at
  or before the cursor) with a map ghost. The Evidence Workbench gains lap
  pickers and a track-context map.

**Tech Stack:** Python 3.11 / FastAPI / pydantic v2; React 18 / TypeScript /
vitest; hand-rolled SVG. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-28-phase-12c-spatial-evidence-design.md`

## Global Constraints

- **Rules**
  - The 12B commands, TDD red-first, and the commit prefix `phase12c:`.
  - Changed Python files must be ruff-clean. ESLint: 0 errors.
  - Frontend tests run with `npx vitest run --no-file-parallelism`.
- **Evidence**
  - `evidence_v1` is unchanged: same schema, builder and versions.
  - The same canonical rows give a byte-identical evidence body from
    either source.
  - Header `X-Data-Source: recording | database` on `/laps`,
    `/telemetry/{driver}`, `/evidence/lap-comparison` and its `/spatial`.
- **Source selection:** the recording when `index_recordings` has the
  session, else the database, else 404.
- **Store**
  - Version `recording-store-1.0.0`.
  - Files next to the recording: `laps_v1.json`, `telemetry_car_v1.bin`,
    each with a `.key` file of the form `version|size|mtime_ns`.
  - A mismatch, truncation or parse error triggers a rebuild, never a
    serve.
- **Duplicates (ruling)**
  - Lap rows: the later row wins (the 12A and timeline rule).
  - Car samples: identical duplicates collapse to one; conflicting samples
    at the same instant are dropped and counted.
  - Byte equality with the DB (which keeps the first row) is asserted only
    for recordings with zero conflicts.
- **Nulls:** a null stays `None`, never 0. The RAW telemetry route omits
  null samples per channel; a gap is never filled.
- **Laps:** `deleted` is `true` only from a `LapCorrection`; otherwise it is
  `null`.
- **Telemetry window:** `[t − 60 s, t + 60 s]`; only samples at or before t
  are drawn; a gap over 2 s breaks the line and is labelled.

## Review Focus

1. **The cursor moves back past loaded telemetry.** No sample after t is
   ever drawn. Test: Task 5 (`never draws a sample after the cursor after
   seeking back`).
2. **A telemetry window for another driver or session arrives late.** It is
   refused, and the latest request wins. Test: Task 5 (`drops a late window
   for a previous driver`).
3. **An evidence segment's samples fall in the pit lane or outside
   coverage.** The extent is NOT_PLACED with its reason and is never drawn.
   Tests: Task 3 (`test_pit_lane_extent_not_placed`) and Task 7 (`draws
   only PLACED extents`).
4. **The DB is down.** `/sessions` still lists recorded sessions, and the
   pickers work. Tests: Task 2 (`test_sessions_lists_recorded_without_db`)
   and Task 7 (`pickers work from recorded sessions`).
5. **A lap without a duration in the recording.** It gets 422, and no
   window is guessed. Test: Task 2 (`test_lap_without_duration_is_422`).

---

### Task 1: Recording store (laps + car telemetry)

**Files:**
- Create: `backend/app/storage/recording_store.py`
- Modify: `backend/app/spatial/source.py`
  - export `check_row = _check` (the existing identity guard, unchanged);
  - `SpatialIdentityError` is the identity error.
- Test: `backend/tests/test_recording_store.py` (synthetic recording via
  the helpers `test_spatial_source.py` already uses)

**Interfaces:**
- Consumes:
  - `iter_recording_models(frames_path, include_types, count_markers=None,
    counts=None)`;
  - `index_recordings(root) -> {sid: dir}`;
  - `SourceInfo` (`app/evidence/lap_comparison.py:59`).
- Produces:
```python
STORE_VERSION = "recording-store-1.0.0"
class RecordingStore:
    def __init__(self, recordings_dir: Path) -> None: ...
    def recording_for(self, session_id: str) -> Path | None: ...
    def session_source(self, session_id: str) -> SourceInfo: ...
    def lap(self, session_id: str, driver: int, lap: int) -> Lap: ...                # LookupError if unknown
    def lap_catalog(self, session_id: str) -> dict: ...                           # Repository.session_lap_catalog shape
    def car_samples(self, session_id: str, driver: int,
                    t0: datetime, t1: datetime) -> list[TelemetryCarSample]: ...  # inclusive, time-sorted
    def counts(self, session_id: str) -> dict[str, int]: ...                       # rows, duplicates, conflicts
```

- [ ] **Step 1: Write the failing tests.**
  - `test_null_speed_round_trips_as_none`
  - `test_identical_duplicate_collapses`
  - `test_conflicting_duplicate_dropped_and_counted`
  - `test_later_lap_row_wins`
  - `test_deleted_true_only_from_correction_else_none`
  - `test_other_session_row_raises_identity_error`
  - `test_window_is_inclusive`
  - `test_mtime_change_rebuilds`
  - `test_truncated_bin_rebuilds`
  - `test_catalog_keys_match_repository_shape`
  - `test_has_car_telemetry_means_a_sample_inside_the_lap_window`
- [ ] **Step 2: Run them.** Run: `.\.venv\Scripts\python.exe -m pytest
  tests\test_recording_store.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** One pass over the recording, reading
  `SessionInfo`, `Driver`, `Lap`, `LapCorrection` and `TelemetryCarSample`,
  with every row passing `check_row`.
  - `.bin` layout per driver:
    - `t` as `array('d')`;
    - `rpm`, `speed`, `drs` as `'l'`, and `gear` as `'b'`, with sentinel
      −1 for null;
    - `throttle` and `brake` as `'d'`, with NaN for null;
    - the provenance-class letter as `'b'`.
  - Header JSON: key, drivers, lengths, counts. Reads go through `bisect`.
- [ ] **Step 4: Run.** Expected: PASS. Then ruff the changed files.
- [ ] **Step 5: Commit** `phase12c: recording store for laps and car telemetry`.

### Task 2: Source selection on the existing routes

**Files:**
- Modify: `backend/app/api/__init__.py`
  - `_recording_store()` is a module singleton over the recordings dir (the
    same setting the timeline and spatial routes use).
  - `/sessions` gains `recorded` (built from `meta.json`, before DB access),
    with `source: "recording"`.
  - `/laps`, `/telemetry/{driver}` and `/evidence/lap-comparison` use the
    recording when present and set `X-Data-Source`.
  - A telemetry `?lap=` on a lap without a duration returns 422 from the
    recording path.
- Test: `backend/tests/test_recording_routes.py` (synthetic);
  `backend/tests/test_recording_real.py` (Dutch GP; skip without the
  recording, with the reason).

- [ ] **Step 1: Write the failing tests.**
  - `test_evidence_bytes_equal_direct_builder` (recording route bytes ==
    `to_canonical_json(build_lap_comparison_evidence(...))` over the store's
    rows).
  - `test_data_source_header_recording`
  - `test_db_and_recording_evidence_identical` (Postgres required; skip
    with the reason).
  - `test_lap_without_duration_is_422`
  - `test_unknown_lap_is_404`
  - `test_raw_telemetry_returns_every_non_null_sample`
  - `test_sessions_lists_recorded_without_db`
  - Real: `test_dutch_gp_pair_evidence_builds_and_validates`. The pair is
    pinned by the Task 4 script (the fastest timed laps with car telemetry
    of the P1 and P2 finishers); `parse_evidence` round-trips.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests plus `test_evidence_api.py`,
  `test_discovery_api.py` and `test_timeline_api.py`. Expected: PASS (DB
  tests skip).
- [ ] **Step 5: Commit** `phase12c: recording-backed laps, telemetry and evidence routes`.

### Task 3: `evidence_spatial_v1`

**Files:**
- Modify: `backend/app/spatial/state.py`: add `driver_state(index:
  SpatialIndex, driver: int, t: float) -> dict | None`, a public wrapper of
  `_entry` (None when the driver has no track).
- Modify: `backend/app/spatial/contract.py`: add `EvidenceSpatialV1`
  (strict, extra=forbid) and `validate_evidence_spatial(doc, evidence)`.
- Create: `backend/app/spatial/evidence_spatial.py`:
  - `BUILDER_VERSION = "evidence-spatial-1.0.0"`;
  - `place_evidence(evidence: dict, index: SpatialIndex, track: dict) -> dict`.
- Modify: `backend/app/api/__init__.py`: add `GET
  /sessions/{sid}/evidence/lap-comparison/spatial`, with headers
  `X-Spatial-Contract: evidence_spatial_v1`, `X-Evidence-Id` and
  `X-Data-Source`.
- Test: `backend/tests/test_evidence_spatial.py`, plus a real case in
  `test_recording_real.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_placed_extent_equals_driver_state_at_ts_range`
  - `test_no_data_segment_not_placed_no_telemetry`
  - `test_pit_lane_extent_not_placed`
  - `test_off_reference_extent_not_placed`
  - `test_outside_coverage_not_placed`
  - `test_polyline_endpoints_equal_from_to_xy`
  - Tamper, each refused: another `evidence_id`, segments reordered,
    PLACED without a fraction, NOT_PLACED with a polyline, fraction ≥ 1,
    extra field.
  - `test_unvalidated_track_409_with_reasons`
  - `test_no_recording_404`
  - `test_corner_limitation_when_corner_gate_failed`
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** The extent runs forward from `from_fraction`
  to `to_fraction` and wraps at the line. The polyline is
  `Centerline.subpath(s0, s1)`.
- [ ] **Step 4: Run.** Expected: PASS. Ruff.
- [ ] **Step 5: Commit** `phase12c: evidence placed on the track by sample time`.

### Task 4: Real fixtures and measurements

**Files:**
- Create: `scripts/evidence_fixture.py [--measure]`, writing
  `frontend/tests/fixtures/evidence/dutch_gp_pair.json` with:
  - the pair, the evidence, `evidence_spatial`, the laps catalog subset;
  - driver A's RAW telemetry for 120 s around LAP 40, plus the matching
    spatial trace.

- [ ] Run the script. Measure:
  - store cold build and warm load;
  - the 120 s telemetry window (bytes, latency);
  - the evidence and `/spatial` routes (median of 15).
- [ ] Ledger the numbers in
  `.superpowers/sdd/2026-09-28-phase-12c-spatial-evidence/progress.md`.
- [ ] **Commit** `phase12c: real evidence fixture and measurements`.

### Task 5: Telemetry data layer (frontend)

**Files:**
- Create:
  - `frontend/src/telemetry/types.ts`;
  - `frontend/src/telemetry/api.ts`: `fetchTelemetryWindow(sid, driver,
    fromMs, toMs, signal) -> Promise<TelemetryWindowDoc>`, fail closed on
    session, driver and window echo; reads `X-Data-Source`;
  - `frontend/src/telemetry/useTelemetryWindow.ts`:
    `useTelemetryWindow({sid, driver, t, playing})` returns `{status,
    channels (samples ≤ t), gaps, reason, retry}`, debounced 120 ms, latest
    wins, and prefetches the next window while playing.
- Test: `frontend/tests/telemetry/telemetry.test.ts` (real fixture)
  - `never draws a sample after the cursor after seeking back`
  - `splits at gaps over 2 s`
  - `drops a late window for a previous driver`
  - `reports DRS unavailable when every sample is null`
  - `keeps nulls out of the series (not zero)`

- [ ] Red → implement → green → commit `phase12c: telemetry window client`.

### Task 6: Car telemetry panel and map ghost

**Files:**
- Create: `frontend/src/components/telemetry/CarTelemetryPanel.tsx`
  (memoized; grid area `telemetry` below focus; Timing tab on phones).
- Modify:
  - `frontend/src/components/spatial/TrackMap.tsx`: add the prop `ghost:
    {driver, at, x, y} | null`;
  - `frontend/src/components/command/CommandCenter.tsx` plus its CSS grid.
- The ghost comes from `/spatial/{driver}?from&to` samples at or before the
  hovered time, within 2 s.
- Test: `frontend/tests/telemetry/panel.test.tsx`
  - `renders channels with a hidden table`
  - `labels a gap`
  - `ghost sits at the sample's own x/y`
  - `no ghost beyond 2 s`
  - `Esc clears the ghost`
  - `asks to select a driver when none is selected`

- [ ] Red → implement → green → commit `phase12c: car telemetry at the cursor with a map ghost`.

### Task 7: Evidence Workbench on the map

**Files:**
- Create:
  - `frontend/src/evidence/spatial.ts`: fail closed on `evidence_id` and
    `track_id`;
  - `frontend/src/components/evidence/LapPickers.tsx`: offers only laps
    with a duration and car telemetry; prefills the lap length and its
    source from the track citation;
  - `frontend/src/components/evidence/TrackContext.tsx`: A solid, B
    dashed; a tick for each placed segment; NOT_PLACED listed; a click
    selects `seg`; "Track context unavailable" plus the reason without a
    validated track.
- Modify:
  - `EvidenceWorkbench.tsx` and `ComparisonForm.tsx`;
  - FocusPanel's "Compare laps" link (the focused driver's last completed
    lap).
- Test: `frontend/tests/evidence/spatial.test.tsx`
  - `draws only PLACED extents`
  - `pickers work from recorded sessions`
  - `pickers offer only laps with a duration and telemetry`
  - `prefills lap length with its citation`
  - `seg survives in the URL`
  - `Singapore shows Track context unavailable`
  - `refuses evidence_spatial for another evidence_id`

- [ ] Red → implement → green → commit `phase12c: workbench pickers and track context`.

### Task 8: QA, performance, mutations, docs, final review

- [ ] Browser QA at 375, 768, 1024, 1440 and 1920 px on the Dutch GP (API
  :8010, Vite :5180). Extend `scripts/bench_playback.mjs` with the
  telemetry panel open.
- [ ] Mutations: the spec §11 list, one at a time, each restored.
- [ ] Docs:
  - `docs/PHASE_12C_SPATIAL_EVIDENCE.md`, MASTER.md §15, and the
    `X-Data-Source` note in the RaceWise contract;
  - CLAUDE.md "Current state" and "Baseline";
  - `docs/PHASE_12_SPATIAL_INTELLIGENCE.md` table.
- [ ] Full backend and frontend suites, build and lint; then commit
  `phase12c: QA, performance, mutations and documentation`.
- [ ] Final Opus review of the branch, one fix pass (red-first per
  finding), and the report.
