# Phase 12B — Track Map in the Command Center (design)

Status: design approved in conversation 2026-09-26; this document awaits
review. Branch: `phase-12-spatial-intelligence` (12A is committed there;
the branch is stacked on phase 11).

12B shows the validated 12A spatial evidence in the Phase 11 command center.
The chain is: `track_reference_v1` + `spatial_state_v1` → the ONE global
cursor → the track map.

12B adds no spatial algorithm, no second clock, no AI and no prediction.

## 1. What 12B answers

- Where are the cars at this session moment?
- What sector is each car in?
- Where is the selected driver, or the selected battle pair, relative to the
  circuit?
- What spatial information is actually validated?

## 2. Decisions

1. **The one cursor becomes race time `t`** (user decision, 2026-09-26).
   Lap frames are derived from `t`, and replay plays race time.
2. **The design is approved in conversation** (2026-09-26), covering §3–§13.
3. **`MASTER.md` is authoritative for visuals.** From the invoked taste
   skills, only what fits an engineering instrument is taken:
   square-cornered framing, 1 px dividing grids, monospace metadata strips
   and corner registration marks.
   - Rejected: perpetual motion, glow, scanlines, new fonts and Tailwind.

## 3. Architecture

```
recording -> 12A builder -> track_reference_v1 (+ sectors[])      [backend]
                         -> spatial_state_v1 (+ sector)            [backend]
                         -> spatial_window_v1 (states on a grid)   [backend, new route]
frontend:
  ui.t (ONE cursor, race time)
    -> frameAt(t) -> buildMoment(timeline, index, t)   every Phase 11 panel
    -> useSpatial(sid, t, playing)                      track once; state at/before t
    -> <TrackMap>                                       render only
```

**Browser responsibilities.** The browser:
- selects the state at or before `t`, the frame at or before `t`, and items
  timestamped at or before `t`;
- orders and formats;
- does rendering geometry only: coordinates to pixels, tick orientation and
  label placement.

It computes no position, distance, sector, lap, confidence, gap or battle.

## 4. Cursor model (Phase 11 change)

**State.** `UiState.t` (epoch ms, UTC) replaces `index` as the
authoritative cursor. `index` is derived: `frameAt(timeline, t)` = the last
frame whose `at ≤ t` (the START frame when `t` precedes every frame). The
bounds are `tMin` = the START `at` and `tMax` = the FINAL `at`.

**Actions**

| action | effect |
|---|---|
| `load{tMin, tMax, t}` | initial cursor and bounds |
| `seekTime{t}` | clamped to the bounds |
| `seekFrame{index}` | sets `t` to that frame's `at` |
| `step{by}` | moves by frames |
| `play` / `pause` / `toggle` | playback |
| `tick{wallMs}` | while playing, `t += wallMs × rate`; stops at `tMax` |
| `rate{rate}` | rate ∈ {1, 4, 16, 64} × race time |
| selection actions | unchanged |

**Playback.** A single `requestAnimationFrame` loop in `usePlayback`
dispatches `tick` with the elapsed wall time. Each tick is capped at 250 ms,
so a hidden tab never jumps the race. This is the one clock; no panel owns a
timer.

**Moment.**
- `buildMoment(timeline, index, t?)` keeps every Phase 11 field.
- With `t`, race control, pits, weather and events are the items with
  `ts ≤ t`. Items without `ts` fall back to `frame_index ≤ index`.
- It adds `moment.t` and `moment.frameAt` (the ISO `at` of the frame).
- The panels that read frame rows (timing tower, positions, battles,
  strategy) are labelled "as of LAP k · hh:mm:ss".

**URL.**
- `?lap=` is the derived frame token.
- `?t=<ISO UTC>` is written only when `t` differs from that frame's `at`.
- On read: a valid, in-range `?t=` wins, otherwise `?lap=`, otherwise
  `tMax`.

**Keyboard.**
- ←/→: step one frame.
- Shift+←/→: ±10 s of race time.
- Space/K: play or pause.
- Home/End: the bounds.

**Replay bar.**
- The scrubber is an `input[type=range]` over seconds from `tMin`.
- It is segmented by the phase of each frame's interval.
- The rate buttons read "1× 4× 16× 64× race time".
- The readout shows the frame label plus the UTC clock of `t`.

## 5. Backend additions

These only expose 12A; no algorithm changes.

**5.1 `sector` on state and trace entries.**
- The values are `1 | 2 | 3 | null`.
- The rule, using lap fractions from the measured finish line: 1 if the
  fraction is below S1's, 2 if below S2's, 3 otherwise. It is null when
  there is no fraction.
- The line fractions are stored on the index and persisted in the cache
  header.
- Validator: `sector` is present exactly when `reference_fraction` is.

**5.2 `sectors[]` on `track_reference_v1`** (validated tracks only; `[]` when
unvalidated). Each entry has:
- `sector`, `from_line`, `to_line` (FINISH→S1, S1→S2, S2→FINISH);
- `length_m`;
- `polyline`: the reference from the from-line point to the to-line point,
  with the line points inserted exactly;
- `label_point`: the reference point at the sector's middle.

Built with a new `Centerline.subpath(s0, s1)` (additive, wraps the loop).

Validator:
- exactly 3 sectors, contiguous, only when validated;
- each polyline starts and ends at its lines' `(x, y)`;
- the lengths sum to the cited length (1e-6).

**5.3 `GET /api/v1/sessions/{sid}/spatial/window?from=&to=&step=`** returns
`spatial_window_v1`.

Envelope fields:
- `contract_version`, `builder_version`, `session_id`, `track_id`;
- `from_ts`, `to_ts`, `step_s`;
- `lap_length_m`, `line_placement_p95_m`, `limitations`;
- `states[]`: `{at, drivers[]}`. The driver entries are exactly
  `spatial_state_v1` entries.

Limits and errors:
- `0 < to − from ≤ 120 s`;
- `0.25 ≤ step ≤ 10 s`;
- at most 481 states;
- the same 404 / 409 / 422 / 500 as the other spatial routes.

Why this route exists: the API allows 120 requests per minute per client,
so a request per replay tick is impossible. At 16× a 120 s window lasts
7.5 s of wall time, about 8 requests per minute.

**5.4 Versions.**
- `SPATIAL_BUILDER_VERSION` stays `spatial-builder-1.0.0`: the fields are
  additive and no existing value changes meaning.
- The `track_id` is unchanged (`trk1_5c46f956e6753d06f8583341`).
- Cached documents without the new fields fail the stricter contract and are
  rebuilt (fail safe).
- The golden is regenerated.

## 6. Frontend data layer (`frontend/src/spatial/`)

- **`types.ts`:** a mirror of the three contracts plus `spatial_window_v1`.
- **`api.ts`:** `fetchTrack`, `fetchStateAt` and `fetchWindow`. They fail
  closed on:
  - a wrong `X-Spatial-Contract` or `contract_version`;
  - a `session_id` other than the requested one;
  - a `track_id` that differs from the loaded track's;
  - drivers that are unsorted or duplicated.

  HTTP errors map to the existing `ApiError` kinds; 409 becomes
  `unvalidated`, carrying the backend's `reasons`.
- **`useSpatial(sid, t, playing)`:**
  - **Track:** loaded once per session. On a session change every spatial
    value is cleared before anything new is shown.
  - **While playing:** windows of 120 s at a 0.5 s step (1 s at 16×, 2 s at
    64×) are prefetched ahead of `t`. The shown state is the window state
    with the largest `at ≤ t` (selection).
  - **While paused or scrubbing:** one `?at=t` request, debounced by 120 ms.
    The exact backend state is shown once it arrives.
  - **Cache:** windows are cached per `(sid, track_id, from, step)` and are
    never shared across sessions.
  - **Labelling:** the map always states which `at` it shows ("positions at
    13:41:02.5Z"). When that `at` trails the cursor by more than one step it
    also says "positions lag the cursor".

## 7. `<TrackMap>` (SVG, no dependency)

**Coordinates.** Fit the validated polyline's bounding box to the panel,
preserving the aspect ratio (uniform scale, no distortion). Feed y is drawn
upward; to be verified in the plan, see §14. No axis is labelled in metres.

**Layers**, bottom to top, following the brief's hierarchy:

| layer | drawing |
|---|---|
| circuit | one quiet 6 px stroke of the reference |
| sectors | the `sectors[]` paths, 2 px; S1/S2/S3 labels at their `label_point` |
| markers | driver markers |
| selection | the selected driver's halo and label, and the battle pair's connector |
| timing lines | FINISH/S1/S2 short ticks perpendicular to the path, labelled |
| status | the phase banner from `moment.frame.phase` (RED FLAG, VSC, SC) |

Sector strokes use neutral tones (`--border-*` and `--text-muted`, not
driver or verdict colours).

**Markers**, by 12A state:

| state | marker |
|---|---|
| POSITIONED + ON_REFERENCE | solid team-colour dot with a 1 px ink ring |
| POSITIONED + OFF_REFERENCE | hollow team-colour ring + "OFF" tag |
| POSITIONED + PIT_LANE | small square + "PIT" tag (no pit path drawn) |
| STALE | 50% opacity + clock glyph + age in the tooltip |
| NO_COVERAGE | no marker; listed in a "Not on map" strip with its status |

Confidence LOW or NONE gives a dashed ring, and the grade is always in words
in the tooltip and table.

**Labels.**
- **Persistent:** the selected driver, the battle pair, and the P1 row of
  the current frame.
- **On hover or focus:** any car.
- **Placement:** greedy, collision-avoiding, on four candidate offsets.

**Tooltip** (hover or focus), concise:
- code and number, status and flag;
- lap, sector, distance (metres from the finish line), confidence;
- age, when STALE.

**Interaction.**
- Hovering a car shows its tooltip; clicking it selects it (the global
  `ui.driver`).
- The battle pair comes from Phase 11 `ui.battle`.
- Hovering a sector highlights its path and shows its label.
- Clicking a timing line shows its measured p95 and n (from the track
  document).
- The camera never moves; the whole circuit stays visible.

**Hooks for 12C.**
- `onPositionSelect(driver, stateAt)` is emitted when a marker is chosen.
- The shown state is exposed via `useSpatial`.

## 8. Map states

| state | when | shows |
|---|---|---|
| LOADING | the track or first state is loading | a skeleton frame with a shimmer, no stale session content |
| READY | a validated track and a state for the cursor | the map |
| PARTIAL | some drivers are NO_COVERAGE or STALE | the map plus the "Not on map" strip |
| STALE | the shown state trails `t` by more than one step | the map plus a "positions lag the cursor" note |
| UNAVAILABLE | 409 unvalidated / 404 no recording / a live hub (RECORDING_ONLY) | the reason and the gate reasons; no circuit drawn |
| ERROR | 422 / 500 / network | the message and a retry |

## 9. Information drawer

This is a compact toggle; it is not shown by default.
- **Provenance:** source (OpenF1 recorded location feed), session, contract,
  status, `track_id`, reference lap, input digest prefix.
- **Capabilities:** Map, Sectors, Timing lines, Driver position are
  validated. Racing line, Corners, DRS zones, Pit-lane path are
  unavailable, each with its evidence line from the contract.
- **Precision:** the line placement p95 per line, and "no corner-level
  distances".
- **Legend:** marker states, selection, sectors, timing lines.

## 10. Layout and responsiveness

| width | layout |
|---|---|
| ≥ 1440 | timing \| **track map** (top of the centre column) above position evolution and battles \| focus; strategy \| race control and weather below |
| 1024–1439 | two columns: timing and focus \| track map, position chart, battles |
| < 1024 | one column: timing, focus, **track map**, chart, battles, … |
| < 760 | tabs Timing / **Track** / Race / Strategy / Events; Track is the map full-width with the selected-driver strip |

- There is no horizontal overflow at 375/768/1024/1440/1920.
- The map's height follows its container width at the circuit's aspect
  ratio, with a floor and a ceiling.

## 11. Accessibility

- Markers are focusable, with a roving tabindex: ↑/↓ moves through cars in
  the current frame's position order and Enter selects.
- Each marker has an accessible label, e.g. "#63 RUS, positioned on
  reference, lap 16, sector 2, 3412 metres, confidence high".
- A visually hidden table lists every car's spatial state in words.
- Focus is visible (a 2 px ring). Contrast is AA against
  `--background-panel`.
- No meaning relies on colour alone: status tags use words and shapes.

## 12. Motion

- Marker moves between consecutive shown states are a CSS transform
  transition of `min(step / rate, 250 ms)`: rendering only, never data.
- Selection halo: 120 ms. Drawer reveal: a 4 px rise over 200 ms.
- There is no looping animation except the loading shimmer.
- Everything is removed under `prefers-reduced-motion`.

## 13. Performance (to be measured, never claimed)

- first map render;
- a 22-marker update;
- cursor update and scrub;
- playback at 16×, with the request count over 60 s;
- resize;
- selection and battle selection;
- session switch;
- the backend window-route latency for 120 s at 0.5 s.

## 14. Open items measured in the plan

1. **Orientation.** Zandvoort runs clockwise; verify with a cited source. The
   rendered path must travel clockwise with y-up; if not, the rendering
   convention is corrected and recorded.
2. **Window cost.** Measure the payload size and latency on the real
   recording, and adjust the step defaults (§6) if needed.

## 15. Testing

**Backend** (TDD; synthetic plus real):
- the `sector` boundaries and nulls;
- `sectors[]` geometry: contiguity, lengths summing to the cited length,
  endpoints exactly at the lines;
- `Centerline.subpath` wrap;
- the window route: limits, errors, and each state equal to `state_at` at the
  same time;
- the golden regenerated and re-locked;
- the existing 12A suites stay green.

**Frontend** (vitest, jsdom). The real golden track, and a committed fixture
of **real** states generated from the recording by
`scripts/spatial_fixture.py`, cover the brief's 24 cases:
- validated vs unvalidated rendering;
- session identity;
- all drivers;
- selection, and identity colours;
- STALE, NO_COVERAGE and PIT_LANE;
- sectors and timing lines from API data;
- no browser spatial computation (a source scan);
- a cursor change updating the state;
- a session change clearing state;
- battle highlight;
- the red-flag banner from Phase 11;
- replay;
- loading and 404/409/422/500;
- mobile tabs;
- reduced motion;
- keyboard.

The Phase 11 tests are updated to the race-time cursor.

**Mutation checks** (each must be caught):
- the frame derivation off by one;
- list filtering ignoring `ts`;
- a session mismatch accepted;
- a `track_id` mismatch accepted;
- an unvalidated track drawn;
- a NO_COVERAGE marker drawn;
- STALE styled as fresh;
- markers coloured by status instead of identity;
- an interpolated state treated as data;
- the debounce removed;
- the rate cap ignored.

**Browser QA:** 375/768/1024/1440/1920 and the screenshot list in the brief.

## 16. Documentation

- `docs/PHASE_12B_TRACK_MAP.md`;
- a new `MASTER.md` §14 for the map;
- the CLAUDE.md handoff.

The 12A validation report is referenced, not rewritten.

## 17. Out of scope

- telemetry ↔ map synchronization (12C);
- battle geometry and the pit-lane path (12D);
- corners, apexes, DRS zones, racing lines;
- live spatial (12A is RECORDING_ONLY);
- RaceWise, AI, prediction.
