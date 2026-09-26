# Phase 12B Track Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the validated 12A spatial evidence as a track map in the
Phase 11 command center, driven by one race-time cursor that every panel
shares.

**Architecture:**
- **Backend.** It exposes what 12A already computes: a `sector` on each
  state and trace entry, `sectors[]` paths on validated tracks, and a
  batched `spatial_window_v1` route.
- **Cursor.** The frontend makes race time `t` the single cursor, and lap
  frames derive from it.
- **Spatial layer.** `src/spatial/` fetches and selects the evidence,
  failing closed.
- **Map.** An SVG `<TrackMap>` renders it. The browser computes no spatial
  value.

**Tech Stack:**
- Backend: Python 3.11, FastAPI, pydantic v2.
- Frontend: React 18, TypeScript, Vite, vitest (jsdom) and hand-rolled SVG.
- No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-26-phase-12b-track-map-design.md`

## Global Constraints

**Commands**
- Backend, from `backend/`:
  - tests: `./.venv/Scripts/python.exe -m pytest <files> -q`
  - lint: `./.venv/Scripts/python.exe -m ruff check <files>`
  - Changed files must be ruff-clean. Pre-existing lint debt stays as it is.
- Frontend, from `frontend/`:
  - `npx vitest run --no-file-parallelism <files>`
  - `npx tsc --noEmit`
  - `npm run build`
  - `npx eslint <files>`: 0 errors; the 105 existing warnings stay as they
    are.

**Process**
- TDD: every test is red first.
- Commit messages start with `phase12b:` and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Versions**
- No new dependency.
- `SPATIAL_BUILDER_VERSION` stays `spatial-builder-1.0.0`.
- `track_id` stays `trk1_5c46f956e6753d06f8583341`.
- New contract: `spatial_window_v1`.

**The browser computes no spatial or race value.** That includes position,
distance, sector, lap, confidence, gap and battle.
- It may select (≤ t, bisect), format, and do rendering geometry: the fit
  transform, tick orientation and label placement.
- Visual tweens are CSS transitions only.

**Visuals**
- Use `MASTER.md` tokens only.
- Driver colour shows identity only; status is always in words or shape.
- Numerals are tabular.
- No text claiming corners, apexes, DRS zones, racing lines or a pit-lane
  path. The only exception is the capability lines that say these are
  unavailable.

**Limits**
- Window: 120 s long, step 0.25–10 s, at most 481 states.
- Playback: rates {1, 4, 16, 64} × race time.
- Tick cap: 250 ms of wall time.
- Scrub debounce: 120 ms.
- Replay step: 0.5 s at 1–4×, 1 s at 16×, 2 s at 64×.

## Review Focus

1. **The cursor is at FINAL or after location coverage ends.** Every car is
   NO_COVERAGE.
   - Expected: the map says "No position coverage at this moment" and draws
     no markers. It is neither blank nor showing stale positions.
   - Test: Task 7.
2. **An out-of-order response.** A slow `?at=t1` response arrives after
   `?at=t2` was requested.
   - Expected: it is never shown as current; the latest request wins.
   - Test: Task 5.
3. **A hidden tab during playback.** One tick of 5,000 ms wall time arrives.
   - Expected: `t` advances by at most 250 ms × rate.
   - Test: Task 4.
4. **Route shadowing.** `/spatial/window` could be captured by
   `/spatial/{driver_number}`.
   - Expected: the window route answers, not a 422 from the driver route.
   - Test: Task 3.
5. **A malformed or out-of-range `?t=` in the URL.**
   - Expected: it is ignored; the cursor falls back to `?lap=`, then to the
     end, with no crash.
   - Test: Task 4.

---

### Task 1: Sector paths on validated tracks

**Files:**
- Modify: `backend/app/analysis/track_geometry.py` (`Centerline.subpath`)
- Modify: `backend/app/spatial/builder.py`
- Modify: `backend/app/spatial/contract.py`
- Test: `backend/tests/test_track_geometry.py`
- Test: `backend/tests/test_spatial_contract.py`
- Test: `backend/tests/test_spatial_real.py`
- Regenerate: `docs/spatial/track_reference_v1_dutch_gp_2026.json`

**Interfaces:**
- Produces:
  - `Centerline.subpath(s0: float, s1: float) -> list[tuple[float, float]]`
    - It returns `point_at(s0)`, then every vertex strictly between s0 and
      s1 going forward, then `point_at(s1)`.
    - On a closed loop with `s1 < s0`, it wraps past the end.
  - Track document field `sectors`, a list of
    `{sector: 1|2|3, from_line, to_line, length_m, polyline: [[x, y], ...], label_point: [x, y]}`.
    - It is `[]` unless the track is validated.

- [ ] **Step 1: Write the failing tests.**
  - `test_subpath_forward_and_across_the_line`, on
    `Centerline(SQ + [SQ[0]])` (the 400-unit square):
    - `subpath(100, 500) == [(100.0, 0.0), (400.0, 0.0), (400.0, 100.0)]`
    - `subpath(1550, 50) == [(0.0, 50.0), (0.0, 0.0), (50.0, 0.0)]`
  - `test_validated_track_publishes_three_contiguous_sectors` (synthetic,
    cited length 4000 m):
    - `[s["sector"] for s in doc["sectors"]] == [1, 2, 3]`;
    - the (from_line, to_line) pairs are FINISH→S1, S1→S2 and S2→FINISH;
    - each polyline starts and ends at its timing lines' `(x, y)`;
    - `abs(sum(length_m) - 4000) < 1e-6`.
  - `test_unvalidated_track_has_no_sectors`: `doc["sectors"] == []`.
  - `test_tampered_documents_are_rejected` gains two cases:
    - sectors present on an UNVALIDATED track;
    - lengths that do not sum to the cited length.
- [ ] **Step 2: Run them. Expected: FAIL** (no `subpath`, no `sectors` key).
- [ ] **Step 3: Implement.**
  - `Centerline.subpath`: use `bisect` over the existing cumulative
    lengths.
  - `builder._sector_docs(ref, lines, length_m)`:
    - a line's arc position is `s = fraction × total_length`;
    - `length_m = ((to.fraction − from.fraction) % 1) × length_m`;
    - `label_point = point_at(from_s + span / 2)`.
  - Contract model `SectorGeometry` and the field `TrackReferenceV1.sectors`.
  - Validator rules:
    - exactly 3 contiguous sectors when validated, and `[]` otherwise;
    - polyline endpoints equal the lines;
    - lengths sum to `circuit.lap_length_m` within 1e-6.
- [ ] **Step 4: Run and regenerate.**
  - Run the contract, geometry and store tests. Expected: PASS.
  - Run `../scripts/spatial_report.py --write-golden` with the venv python.
  - Diff the golden as JSON. The only difference must be the new `sectors`
    key, and `track_id` must be unchanged.
  - Add `test_real_sectors_follow_the_measured_lines`: the lengths sum to
    4259, and the endpoints equal the published lines.
  - Run `pytest tests/test_spatial_real.py -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `phase12b: sector paths on validated tracks`.

### Task 2: A sector on every state and trace entry

**Files:**
- Modify: `backend/app/spatial/state.py`
- Modify: `backend/app/spatial/builder.py`
- Modify: `backend/app/spatial/contract.py`
- Modify: `backend/app/storage/spatial_store.py`
- Test: `backend/tests/test_spatial_state.py`
- Test: `backend/tests/test_spatial_contract.py`
- Test: `backend/tests/test_spatial_store.py`
- Test: `backend/tests/test_spatial_real.py`

**Interfaces:**
- Produces:
  - `SpatialIndex.line_fractions: dict[str, float] | None = None`
    - S1 and S2 lap fractions measured from the finish line, as
      `{"S1": f1, "S2": f2}`.
    - Persisted in the index header.
  - State and trace entries gain `sector: 1 | 2 | 3 | None`:
    - `1` when `f < f1`, `2` when `f < f2`, otherwise `3`;
    - `None` when the fraction is None.

- [ ] **Step 1: Write the failing tests.** Synthetic data puts S1 at 1/3 and
  S2 at 2/3 of the lap.
  - `test_sector_follows_the_measured_lines`: car 1 is in sector 1 at 75 s
    (fraction 0.25), sector 2 at 85 s (0.4167) and sector 3 at 105 s (0.75).
  - `test_no_fraction_means_no_sector`: a PIT_LANE state has
    `sector is None`.
  - A contract tamper case: a sector with a null fraction is rejected.
  - A store round trip keeps `line_fractions`.
  - `test_real_sector_agrees_with_the_published_lines`: at 50 seeded times,
    each positioned entry's sector is consistent with its `distance_m`
    against the track's S1 and S2 `distance_m`. Entries within 1e-6 m of a
    line are skipped.
- [ ] **Step 2: Run them. Expected: FAIL.**
- [ ] **Step 3: Implement.**
  - The builder fills `line_fractions` with `(line.fraction − finish) % 1`.
  - `state._sector(index, f)` is used by both the state and trace entry
    builders.
  - Contract field `sector`, plus the rule that it is present exactly when
    `reference_fraction` is.
  - The store header carries `line_fractions`.
- [ ] **Step 4: Run the synthetic and real spatial suites. Expected: PASS.**
- [ ] **Step 5: Commit:** `phase12b: sector on spatial state and trace entries`.

### Task 3: The batched window route and a real frontend fixture

**Files:**
- Modify: `backend/app/spatial/contract.py`
- Modify: `backend/app/spatial/builder.py`
- Modify: `backend/app/api/__init__.py`
- Create: `scripts/spatial_fixture.py`
- Create (generated): `frontend/tests/fixtures/spatial/dutch_gp_states.json`
- Test: `backend/tests/test_spatial_api.py`
- Test: `backend/tests/test_spatial_contract.py`
- Test: `backend/tests/test_spatial_real.py`

**Interfaces:**
- Produces:
  - `WINDOW_CONTRACT = "spatial_window_v1"` and `validate_window(doc)`.
  - `window_doc(index, t0: datetime, t1: datetime, step_s: float) -> dict`.
    - Keys: `contract_version`, `builder_version`, `session_id`,
      `track_id`, `from_ts`, `to_ts`, `step_s`, `lap_length_m`,
      `line_placement_p95_m`, `states: [{at, drivers}]` and `limitations`.
    - `states[k].at = t0 + k·step`, up to and including t1.
  - Route `GET /api/v1/sessions/{sid}/spatial/window?from=&to=&step=`.
    - `step` defaults to 0.5.
    - Header `X-Spatial-Contract: spatial_window_v1`.
    - Registered **before** `/spatial/{driver_number}`.
  - The fixture JSON:
    - `states_at`: `spatial_state_v1` documents at the `at` of LAP 2 (red
      flag), LAP 10, LAP 40 and FINAL;
    - `window`: a `spatial_window_v1` of 10 s from LAP 40's `at`, step
      0.5 s;
    - a provenance header
      `{"source": "scripts/spatial_fixture.py", "recording": "openf1-11353-race", "track_id": ...}`.

- [ ] **Step 1: Write the failing tests.**
  - `test_window_states_equal_the_state_at_each_time`: every
    `states[k].drivers == state_doc(index, at_k)["drivers"]`.
  - `test_window_route_limits`:
    - 422 for `to ≤ from`, a window over 120 s, a step below 0.25 or above
      10, and a naive time;
    - 404 with no recording;
    - 409 on an unvalidated track.
  - `test_window_route_is_not_shadowed_by_the_driver_route` (Review
    Focus 4): 200 with the window header.
  - A contract tamper case: unsorted state times are rejected.
  - `test_real_window_matches_state_at`: 20 s at LAP 40, step 1 s.
- [ ] **Step 2: Run them. Expected: FAIL.**
- [ ] **Step 3: Implement.**
  - The model `SpatialWindowV1` reuses the `DriverState` rules.
  - `window_doc`.
  - The route uses the existing UTC parameter parsing and the limits above.
  - `scripts/spatial_fixture.py` loads through `SpatialStore` on the
    recording and writes canonical JSON.
- [ ] **Step 4: Run, generate and measure.**
  - Run the backend spatial suites. Expected: PASS.
  - Run the fixture script. Expected: a file under 400 KB.
  - Measure the window cost on the real recording, 120 s at steps of
    0.5 s, 1 s and 2 s, via TestClient. Record the payload bytes and the
    median of 10 latencies in the ledger.
  - If 0.5 s is over 1.5 MB, ledger a ruling that adjusts the step table.
- [ ] **Step 5: Commit:** `phase12b: spatial window route and real frontend fixture`.

### Task 4: One race-time cursor for the command center

**Files:**
- Modify: `frontend/src/command/state.ts`
- Modify: `frontend/src/command/moment.ts`
- Modify: `frontend/src/command/format.ts`
- Modify: `frontend/src/components/command/CommandCenter.tsx`
- Modify: `frontend/src/components/command/ReplayBar.tsx`
- Modify: `frontend/src/components/command/Shell.tsx` (the `SHORTCUTS`
  list)
- Test: `frontend/tests/command/model.test.ts`
- Test: `frontend/tests/command/command.test.tsx`

**Interfaces:**
- Produces:

```ts
export const RATES = [1, 4, 16, 64] as const;
export const TICK_CAP_MS = 250;
export interface UiState { t: number; frames: number[]; playing: boolean; rate: number;
  driver: number | null; battle: string | null; rcKey: string | null; density: Density }
export type UiAction = { type: "load"; frames: number[]; t: number } | { type: "seekTime"; t: number }
  | { type: "seekFrame"; index: number } | { type: "step"; by: number } | { type: "play" } | { type: "pause" }
  | { type: "toggle" } | { type: "tick"; wallMs: number } | { type: "rate"; rate: number }
  | { type: "driver"; driver: number | null } | { type: "battle"; key: string | null }
  | { type: "event"; key: string | null; t?: number } | { type: "density"; density: Density } | { type: "clear" };
export function frameTimes(t: Timeline): number[];                   // epoch ms of each frame's `at`
export function frameIndexAt(frames: number[], t: number): number;   // last frame <= t; 0 before all
export function buildMoment(t: Timeline, index: number, at?: number): Moment;  // Moment gains t: number
export interface CommandUrl { session: string | null; lap: string | null; t: string | null; driver: number | null }
export function fmtClockTenths(ms: number): string;                  // "13:41:02.5 UTC"
```

**Rules**
- `tMin = frames[0]`, `tMax = frames[frames.length - 1]`; `t` is clamped to
  that range.
- `step`:
  - by −1: go to the current frame's own `at` if `t` is past it, otherwise
    to the previous frame;
  - by +1: go to the next frame.
- `tick`: `t += min(wallMs, TICK_CAP_MS) × rate`, clamped to `tMax`. Playing
  stops at `tMax`.
- `play` at `tMax` restarts from `tMin`.
- `buildMoment` list items: an item with `ts` is included when
  `ts ≤ at`; an item without one is included when `frame_index ≤ index`.
  `at` defaults to `frames[index]`.
- URL: `?t=` (ISO) is written only when `t ≠ frames[index]`. On read, `?t=`
  wins when it is valid and inside `[tMin, tMax]`.
- Keyboard: Shift+←/→ moves ±10,000 ms.

- [ ] **Step 1: Write the failing tests.**
  - `model.test.ts` replaces the Phase 11 reducer block with:
    - `tick advances race time at the rate and stops at the end`;
    - `a hidden-tab tick is capped` (Review Focus 3): `wallMs: 5000` at
      rate 16 gives `t + 4000`;
    - `step back from mid-lap goes to the lap's own frame first`;
    - `frameIndexAt picks the last frame at or before t`;
    - `lists include items timestamped at or before t between frames`: a
      real race-control message whose `ts` lies between two lap frames is
      included at `t = ts` while `index` is still the earlier frame's.
  - `command.test.tsx`:
    - `?t= mid-lap opens between frames`: the tower shows the earlier lap
      frame, and the readout shows `fmtClockTenths(t)`;
    - `a malformed or out-of-range ?t= falls back to ?lap=` (Review
      Focus 5);
    - `Shift+ArrowRight moves 10 s and every panel keeps one moment`.
  - Existing Phase 11 tests keep their assertions. Only their calls change:
    `seek` becomes `seekFrame`, and the speed buttons become the rate
    buttons.
- [ ] **Step 2: Run them. Expected: FAIL.**
- [ ] **Step 3: Implement.**
  - `usePlayback(playing, rate, dispatch)`: a `requestAnimationFrame` loop
    dispatching `tick{wallMs}`, cancelled on pause and on unmount.
  - `ReplayBar`:
    - the scrubber runs over seconds from `tMin`, with `step 0.1`;
    - phase segments come from frame times;
    - rate buttons read "1× 4× 16× 64×", captioned "race time";
    - the readout shows the frame label and `fmtClockTenths(t)`.
  - `CommandCenter`: derive `index = frameIndexAt(ui.frames, ui.t)`, pass
    `ui.t` into `buildMoment`, and keep the URL in sync.
- [ ] **Step 4: Run `npx vitest run --no-file-parallelism tests/command` and
  `npx tsc --noEmit`. Expected: PASS.**
- [ ] **Step 5: Commit:** `phase12b: one race-time cursor for the command center`.

### Task 5: The spatial data layer

**Files:**
- Create: `frontend/src/spatial/types.ts`
- Create: `frontend/src/spatial/api.ts`
- Create: `frontend/src/spatial/useSpatial.ts`
- Modify: `frontend/src/command/api.ts`: add the `"unvalidated"` kind, and
  `reasons: string[]` on `ApiError`
- Test: `frontend/tests/spatial/fixture.ts`
- Test: `frontend/tests/spatial/api.test.ts`
- Test: `frontend/tests/spatial/useSpatial.test.tsx`

**Interfaces:**
- Consumes:
  - the Task 3 fixture;
  - the golden `docs/spatial/track_reference_v1_dutch_gp_2026.json`, read
    in tests the same way `golden()` reads the timeline.
- Produces:

```ts
export function fetchTrack(sid: string, signal?: AbortSignal, f?: typeof fetch): Promise<TrackReference>;
export function fetchStateAt(sid: string, atMs: number, trackId: string, signal?: AbortSignal,
  f?: typeof fetch): Promise<SpatialState>;
export function fetchWindow(sid: string, fromMs: number, toMs: number, stepS: number, trackId: string,
  signal?: AbortSignal, f?: typeof fetch): Promise<SpatialWindow>;
export function stepForRate(rate: number): number;   // 0.5 | 1 | 2
export interface SpatialView { status: "loading" | "ready" | "unavailable" | "error";
  track: TrackReference | null; shown: { at: number; drivers: DriverState[] } | null;
  lagging: boolean; reason: string | null; reasons: string[]; error: ApiError | null; retry: () => void }
export function useSpatial(o: { sid: string; t: number; playing: boolean; rate: number; live: boolean }): SpatialView;
```

**Rules**
- **Fail closed.** Each response is checked for:
  - the contract header and `contract_version`;
  - a session id equal to `sid`;
  - a `track_id` equal to the track's;
  - driver numbers that are sorted and unique.
- **409** becomes `ApiError("unvalidated", message, 409)` with `reasons`.
- **Session change:** clear the track and `shown` before anything new
  renders.
- **Live:** `live` means `unavailable` with reason `RECORDING_ONLY`, and no
  request is made.
- **Paused:** after a 120 ms debounce, request `?at=`. The latest request
  wins: a request counter drops late responses.
- **Playing:**
  - request windows of 120 s with step `stepForRate(rate)`, keyed by
    `(sid, track_id, from, step)`;
  - prefetch the next window once `t` passes the middle of the current one;
  - `shown` is the window state with the largest `at ≤ t`.
- **`lagging`:** `shown.at < t − stepS·1000`.

- [ ] **Step 1: Write the failing tests** (mocked `fetch`, fake timers, real
  fixtures):
  - `accepts the real track and states for its own session`;
  - `refuses another session, another track_id, a wrong contract header`;
  - `409 carries the gate reasons`;
  - `debounces rapid cursor moves to one ?at request`;
  - `an old response arriving late never replaces the newer one` (Review
    Focus 2);
  - `a session change clears the map before the new track arrives`;
  - `playing uses window requests only`: over 60 s of race time at 16×,
    at most 2 window requests and 0 `?at` requests;
  - `live sessions are unavailable without a request`.
- [ ] **Step 2: Run them. Expected: FAIL.**
- [ ] **Step 3: Implement** the three modules.
- [ ] **Step 4: Run `npx vitest run --no-file-parallelism tests/spatial` and
  `npx tsc --noEmit`. Expected: PASS.**
- [ ] **Step 5: Commit:** `phase12b: spatial data layer, fail closed`.

### Task 6: The track map renderer

**Files:**
- Create: `frontend/src/components/spatial/geometry.ts`
- Create: `frontend/src/components/spatial/TrackMap.tsx`
- Create: `frontend/src/components/spatial/spatial.css`
- Test: `frontend/tests/spatial/geometry.test.ts`
- Test: `frontend/tests/spatial/trackmap.test.tsx`

**Interfaces:**
- Consumes:
  - `SpatialView` and the types (Task 5);
  - `Moment` (Task 4);
  - `DriverChip` and the `Icon` exports from `components/command/ui.tsx`.
- Produces:

```ts
export interface Fit { toPx: (x: number, y: number) => [number, number]; width: number; height: number }
export function fitTransform(points: number[][], width: number, maxHeight: number, pad: number, yUp: boolean): Fit;
export function signedArea(points: [number, number][]): number;   // screen coordinates; > 0 = clockwise on screen
export function placeLabels(anchors: { id: number; x: number; y: number }[], w: number, h: number):
  Map<number, { x: number; y: number; anchor: "start" | "end" }>;  // greedy over 4 offsets, no overlap
export function TrackMap(p: { view: SpatialView; moment: Moment; selected: number | null;
  battle: [number, number] | null; onSelect: (d: number | null) => void }): JSX.Element;
```

- [ ] **Step 1: Take the orientation evidence.** This is a measurement and
  comes before any code.
  - Fetch the cited direction of Circuit Zandvoort (the Wikipedia infobox
    "Direction" field).
  - Compute the golden polyline's signed area in feed coordinates, in the
    order of travel.
  - Choose `yUp` so that the on-screen travel direction equals the cited
    one.
  - Ledger the evidence and the choice as a ruling.
- [ ] **Step 2: Write the failing tests.**
  - `fitTransform preserves aspect`: equal x and y scale, and the polyline
    bbox fits inside width, height and padding.
  - `rendered direction matches the cited direction`: the sign of
    `signedArea(golden polyline through toPx)` equals the ruled sign.
  - `trackmap.test.tsx`, on the real golden and the real fixture at LAP 40:
    - `draws the circuit, three sector paths and FINISH/S1/S2 from the contract`
      (tick labels come from the contract line names; sector labels are
      S1/S2/S3);
    - `an unvalidated track draws no circuit and says why`: it shows
      "Spatial map unavailable" and the reasons, with no circuit `path`;
    - `one marker per positioned driver at the backend x/y`: each marker's
      transform equals `toPx(entry.x, entry.y)`;
    - `NO_COVERAGE drivers get no marker and are listed under "Not on map"`;
    - `STALE is faded and labelled stale with its age; OFF and PIT carry their tags`
      (on tampered fixture entries);
    - `marker colour is the driver's team colour whatever the status`;
    - `the selected driver and the battle pair are labelled and highlighted`;
    - `keyboard: arrows move focus through markers in position order; Enter selects; Esc clears`;
    - `the hidden table lists every driver's state in words`;
    - `reduced motion removes marker transitions`, via the `matchMedia`
      mock;
    - `the info drawer lists provenance and validated and unavailable capabilities`;
    - `the browser computes no spatial value`: a source scan of
      `src/spatial/` and `src/components/spatial/` finds no
      `Math.hypot`, no arithmetic on `reference_fraction`, `distance_m` or
      `lap_length_m`, and no marker positioned from the polyline.
- [ ] **Step 3: Run them. Expected: FAIL.**
- [ ] **Step 4: Implement** `geometry.ts` and `TrackMap.tsx`, with one
  memoized component per marker. `spatial.css` uses `MASTER.md` tokens:
  - a square instrument frame with registration corner marks;
  - a monospace metadata strip with `track_id`, the status and
    "feed frame, no metric axes";
  - neutral sector strokes, and tick labels in Plex Condensed;
  - marker motion by `transform` transition only, lasting
    `var(--spatial-tween)`, removed under reduced motion.
- [ ] **Step 5: Run `npx vitest run --no-file-parallelism tests/spatial`,
  `npx tsc --noEmit` and `npx eslint src/components/spatial src/spatial`.
  Expected: PASS with 0 errors.**
- [ ] **Step 6: Commit:** `phase12b: track map renderer`.

### Task 7: Command center integration

**Files:**
- Modify: `frontend/src/components/command/CommandCenter.tsx`
- Modify: `frontend/src/components/command/FocusPanel.tsx`
- Modify: `frontend/src/components/command/command.css`
- Modify: `frontend/tests/command/fixture.ts`: `mockApi` also serves the
  spatial routes from the Task 3 fixture
- Test: `frontend/tests/command/command.test.tsx`

**Interfaces:**
- Consumes: `useSpatial` (Task 5), `TrackMap` (Task 6), `ui.t` and
  `ui.battle` (Task 4).
- Produces:
  - the grid area `map`;
  - the mobile tab `track`;
  - a `FocusPanel` prop `spatial: DriverState | null` feeding a
    "Track position" section.

**Layout** (spec §10)
- **≥ 1440 px:**
  `"timing map focus" "timing chart focus" "timing battles focus" "strategy rc weather"`.
- **1024–1439 px:** the map spans the right column above the chart.
- **< 1024 px:** one column in the order timing, focus, map, chart, battles,
  strategy, rc, weather.
- **< 760 px:** tabs Timing / Track / Race / Strategy / Events.

- [ ] **Step 1: Write the failing tests** in `command.test.tsx`:
  - `the map shows the LAP 40 moment from the real fixture and names its time`;
  - `moving the cursor requests the new moment's state`;
  - `after location coverage ends there are no markers and the map says so`
    (Review Focus 1): at FINAL, every entry is NO_COVERAGE;
  - `the red-flag frame shows the RED FLAG banner from the timeline`;
  - `selecting a driver highlights it on the map and fills Track position in driver focus`;
  - `selecting a battle highlights both cars`;
  - `404, 409, 422 and 500 each show their map state`;
  - `mobile: the Track tab shows the map`.
  - The existing spatial-safety test (no TURN or corner words outside quoted
    race control) must still pass with the map present.
- [ ] **Step 2: Run them. Expected: FAIL.**
- [ ] **Step 3: Implement.** The Track position section shows the status,
  flag, lap, sector, distance, confidence and "positions at" time. Values
  are only formatted.
- [ ] **Step 4: Run the full frontend verification:**
  `npx vitest run --no-file-parallelism`, `npx tsc --noEmit`,
  `npm run build` and `npx eslint .`. Expected: PASS, 0 errors.
- [ ] **Step 5: Commit:** `phase12b: track map in the command center`.

### Task 8: Browser QA, performance, mutations, documentation

**Files:**
- Create: `docs/PHASE_12B_TRACK_MAP.md`
- Modify: `design-system/live-f1-intelligence/MASTER.md` (§14)
- Modify: `design-system/live-f1-intelligence/pages/command-center.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Browser QA** against the real API, with the dev API on :8010
  and Vite on :5180. At 375, 768, 1024, 1440 and 1920 px, check:
  - `scrollWidth ≤ innerWidth`;
  - markers are readable and the selection is clear;
  - there are no console errors;
  - no stale markers remain after a session switch;
  - replay runs.

  Take the brief's screenshots. Fix every defect test-first.
- [ ] **Step 2: Performance.** Using the Performance API in the browser,
  measure:
  - the first map render;
  - a 22-marker update;
  - step and scrub;
  - 16× playback over 60 s: the frame budget and the request count;
  - resize;
  - selection;
  - a session switch.

  Add the backend window latency from Task 3. Report numbers only, and make
  no claim beyond them.
- [ ] **Step 3: Mutation sweep.** Apply each spec §15 mutant alone, run the
  frontend suite, then restore. Target: all killed. For any survivor, add a
  killing test, red first.
- [ ] **Step 4: Documentation.**
  - `PHASE_12B_TRACK_MAP.md`: architecture, API use, cursor, rendering,
    states, limitations, responsive layout, accessibility, performance and
    tests.
  - `MASTER.md` §14: the map's visual rules.
  - `CLAUDE.md`: the handoff and the baseline.
- [ ] **Step 5: Full verification.** Run backend `pytest tests -q`, and the
  frontend vitest, tsc, build and eslint. Record the exact counts.
- [ ] **Step 6: Commit:** `phase12b: QA, performance, mutations and documentation`.
