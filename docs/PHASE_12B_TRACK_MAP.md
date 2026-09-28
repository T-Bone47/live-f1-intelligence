# Phase 12B — Track map in the command center

12B shows the validated 12A spatial evidence in the Phase 11 command center.
Every panel still describes one session moment; the cursor that selects it
is now race time. The browser selects, orders, formats and scales to pixels.
It computes no position, distance, sector, lap, confidence, gap or battle.

- Spec: `docs/superpowers/specs/2026-09-26-phase-12b-track-map-design.md`
- Plan: `docs/superpowers/plans/2026-09-26-phase-12b-track-map.md`
- 12A evidence: `docs/PHASE_12_SPATIAL_INTELLIGENCE.md`, `docs/PHASE_12_SPATIAL_VALIDATION.md`
- Visual rules: `design-system/live-f1-intelligence/MASTER.md` §14 and
  `pages/command-center.md`

It adds no spatial algorithm, no second clock, no AI, no prediction and
nothing RaceWise does.

## 1. Architecture

```
recording -> 12A builder -> track_reference_v1 (+ sectors[])        GET /sessions/{sid}/track
                         -> spatial_state_v1 (+ sector)              GET /sessions/{sid}/spatial?at=
                         -> spatial_window_v1 (states on a grid)     GET /sessions/{sid}/spatial/window
frontend:
  ui.t  (THE cursor, race time)
    -> frameIndexAt(frames, t) -> buildMoment(timeline, index, knownAt)   every Phase 11 panel
    -> useSpatial({sid, t, playing, rate, live})                          select the backend's state
    -> <TrackMap>                                                          render only
```

## 2. Backend additions (expose 12A, no algorithm change)

| addition | what | rule |
|---|---|---|
| `Centerline.subpath(s0, s1)` | the reference from one arc length forward to another, end points inserted exactly, wrapping the loop | additive; every existing value is unchanged |
| `track_reference_v1.sectors[]` | per sector: `from_line`, `to_line`, `length_m`, `polyline`, `label_point` | only on validated tracks; exactly FINISH→S1, S1→S2, S2→FINISH; each path runs line to line; lengths add up to the cited lap (1e-6) |
| `sector` on state and trace entries | 1, 2 or 3 against the measured S1/S2 line fractions; `null` without a fraction | present exactly when `reference_fraction` is |
| `GET /spatial/window?from&to&step` | `spatial_window_v1`: every car at from, from+step, … to | ≤ 120 s, step 0.25–10 s, ≤ 481 states; each state equals `state_at` at that time; registered before `/spatial/{driver}` |

- `SPATIAL_BUILDER_VERSION` stays `spatial-builder-1.0.0` and `track_id` stays
  `trk1_5c46f956e6753d06f8583341`. Caches of the old shape fail the stricter
  contract and are rebuilt (tested). The golden gained only `sectors`.
- Real Dutch GP sectors: S1 1,484.917 m, S2 1,454.246 m, S3 1,319.837 m
  (sum 4,259 m, the cited length); every interior vertex is a reference vertex.
- `scripts/spatial_fixture.py [--measure]` writes the real frontend fixture
  (`frontend/tests/fixtures/spatial/dutch_gp_states.json`, 196,614 bytes:
  states at LAP 2, 10, 40 and FINAL plus a 10 s window) and times the route.

## 3. The race-time cursor (Phase 11 change)

- `UiState.t` (whole epoch milliseconds) is the cursor. The lap frame a
  panel shows is the last frame at or before `t`; frame times come from each
  frame's `at`. A frame without a time (a live lap with no start) is never
  placed at a guessed time: the cursor shows the next timed frame instead,
  or, after the last timed frame, the newest one. A frame time that is not a
  time, or that goes backwards, is refused.
- Actions: `load{frames, t}`, `seekTime`, `seekFrame`, `step` (back goes to
  the lap's own frame first), `nudge{ms}` (Shift+←/→ = ±10 s), `play`,
  `pause`, `toggle`, `tick{wallMs}`, `rate`.
- Playback: one `requestAnimationFrame` loop; `t += min(wallMs, 250) × rate`,
  rates 1×/4×/16×/64× race time. A hidden tab never jumps the race.
- Lists: race control, pit stops and weather are the items timestamped at or
  before `t`; engine events keep the frame the engine first knew them at
  (their own timestamp precedes that frame on 11 of 74 frames).
- The moment object is reused between ticks that change nothing it lists
  (`knownTime`); the frame-row panels, driver focus, the session header and
  the map are memoized with stable callbacks, so a cursor move inside a frame
  re-renders none of them (tested) - only the replay bar and, when the shown
  state changes, the map.
- URL: `?lap=` is the derived frame; `?t=` (ISO with an offset) only while
  the cursor sits between frames. A malformed or out-of-range `?t=` falls
  back to `?lap=`, then to the end.
- Frame-row panels say which frame they show: "as of LAP 40 · 14:26:09".
- Selecting a race-control message moves the cursor to the message's time.

## 4. Spatial data layer (`frontend/src/spatial/`)

| file | role |
|---|---|
| `types.ts` | mirror of the three 12A contracts and `spatial_window_v1` |
| `api.ts` | `fetchTrack`, `fetchStateAt`, `fetchWindow`, `windowForRate` - fail closed |
| `useSpatial.ts` | the backend's state for the cursor; `selectState` |

**Fail closed.** A response is refused unless its `X-Spatial-Contract` header
and body contract match, it belongs to the requested session and the loaded
track, it answers the request (state `at` = requested time; window `from` and
`step` = requested), and it lists each driver once in order. A 409 becomes
`unvalidated` with the gate's reasons.

**Selection, never computation.**
- Paused or scrubbing: one exact `?at=t` request once the cursor has been
  still for 120 ms; only the latest request may land.
- Playing: windows fetched ahead of the cursor; shown = the latest of the
  exact and window states at or before `t` (so starting playback never steps
  back). Window plan per rate, from the measured route cost:

  | rate | span | step | states | wall time between states | requests / min |
  |---|---:|---:|---:|---:|---:|
  | 1× | 60 s | 0.5 s | 121 | 500 ms | 1 |
  | 4× | 120 s | 1 s | 121 | 250 ms | 2 |
  | 16× | 120 s | 2 s | 61 | 125 ms | 8 |
  | 64× | 120 s | 4 s | 31 | 62 ms | 32 |

- A state after the cursor is never shown: after stepping back the map shows
  nothing until the backend answers for the new moment.
- Any cached window may be shown after a rate change (the latest state at or
  before the cursor); only windows at the current step decide what to fetch.
- Nothing is requested before the cursor exists or before the timeline says
  whether the session is live; a session change shows nothing old; a live
  session is unavailable without a request (recordings only).
- A failed window stops window requests until the user retries (no request
  storm against the 120 requests/minute limit); the map shows the error
  with Retry. Paused, the exact state request is independent of it.

## 5. The map (`frontend/src/components/spatial/`)

| file | role |
|---|---|
| `TrackMap.tsx` | container: states, selection, keyboard, layers |
| `MapLayers.tsx` | circuit, sector paths and names, timing lines (memoized per fit) |
| `Markers.tsx` | one memoized marker per positioned car |
| `MapParts.tsx` | tooltip, "Not on map", hidden table |
| `MapInfo.tsx` | provenance, capabilities, precision, legend |
| `geometry.ts` | pixels only: fit, orientation, label placement |
| `words.ts` | every state in words |

What each marker shape means, and every visual rule, is in MASTER.md §14.

**Orientation (measured).** Wikipedia's "List of Formula One circuits" gives
Circuit Zandvoort as clockwise; the golden reference loop has a shoelace area
of −2.23e7 in y-up feed coordinates (clockwise), so feed y is drawn upward and
a test asserts the lap runs clockwise on screen.

**States.**

| state | when | shows |
|---|---|---|
| loading | track or first state loading | skeleton, nothing old |
| ready | validated track and a state | the map, "positions at hh:mm:ss.s UTC" |
| partial | some cars without coverage | markers plus "Not on map" |
| lagging | shown state more than one step before the cursor | "positions lag the cursor" |
| catching up | the cursor stepped back before the last state | no markers, "Loading positions…" until the new state arrives |
| no coverage | every car `NO_COVERAGE` (e.g. FINAL) | the circuit, no markers, "No position coverage at this moment" |
| unavailable | 409 / unvalidated track, 404 no recording, live | the reason and the gate's reasons; no circuit |
| error | 422 / 500 / network | the backend's message and Retry |

## 6. Layout, accessibility, motion

- ≥ 1440 px: the map heads the centre column above position evolution and
  battles. 1024–1439: heads the right column. < 1024: after driver focus.
  < 760: its own Track tab. Height = 0.8 × width, 220–540 px.
- Markers are buttons with full accessible names ("#16 LEC, on reference,
  lap 40, sector 3, 3,501 metres from the finish line, confidence high");
  ↑/↓ move in position order, Enter selects, Esc clears; timing lines are
  buttons. A visually hidden table lists every car in words.
- Driver focus gains "Track position": state, lap, sector, metres from the
  line, confidence and the time the positions are from.
- Motion: marker glide only while playing (`min(step / rate, 250 ms)`),
  none under reduced motion.

## 7. Browser QA (real API, real Dutch GP recording)

Checked at 375, 768, 1024, 1440 and 1920 px: no horizontal overflow at any
width (`scrollWidth = innerWidth`). Continuous playback (1×/4×/16×/64×, a
rate change, pause, stepping back) was run in headless Chrome with
`scripts/bench_playback.mjs` after the in-app browser pane stayed hidden
(§8). Verified on the real data:
- LAP 40: 20 markers, VER and BEA not on the map; P1 NOR and "ANT OFF"
  labelled; starting playback issues one window request (120 s at 2 s).
- LAP 2: RED FLAG banner from the timeline; NOR and ANT `PIT`, RUS and LEC
  `OFF`, the queue along the pit straight.
- FINAL: no markers, "No position coverage at this moment", circuit drawn,
  22 cars listed under "Not on map".
- LEC selected with the RUS–LEC battle: halo, labels, link; Track position
  S3, 3,501 m, high.

Defects found in the browser and fixed test-first:

| finding | fix |
|---|---|
| a `/spatial?at=1970-01-01` request before the timeline loaded | no request until the cursor exists |
| P1 label drawn over the FINISH tag | labels avoid timing-line tags |
| line tags `S1`/`S2` read like the sector names | boxed tags; sector names plain |
| the S1 sector name hidden under cars | sector names 14 px outside the loop, clear of tags |
| rate buttons crowding the transport controls at 375 px | compact group, caption kept in the accessible name |
| the map stepped back 1.1 s when play started | show the latest state at or before the cursor |
| drawer columns breaking the session id at 1440 px | auto-fit columns |

## 8. Performance (measured, never claimed)

| measure | result | method |
|---|---:|---|
| window route, 120 s | 0.5 s step: 241 states, 1.88 MB, 259 ms; 1 s: 0.94 MB, 135 ms; 2 s: 0.48 MB, 74 ms | TestClient on the real recording, median of 10 |
| first load | `/timeline` and `/track` in parallel, ~27 ms each; exact state 15 ms, 9.1 kB | browser resource timing, dev server |
| lap step, keydown → DOM commit | median 75 ms, p90 102 ms (one long task per step); without the map 65 ms | 12 steps, 1440 px, Vite dev build |
| map update after a step | median 328 ms, max 528 ms (includes the 120 ms debounce and the request) | 10 steps, MutationObserver |
| cursor move inside a frame (a playback tick's render path), input to DOM | before the fix pass median 43.9 ms, p90 52 ms; after median 9.7 ms, p90 26.5 ms | 20 scrubber moves of 0.2 s at LAP 40, 1440 px, dev build |
| command-center chunk | 100.27 kB JS (30.65 kB gzip), 39.81 kB CSS (Phase 11: 71.12 kB / 32.09 kB) | `npm run build` |
| playback 16×, 3.75 s wall (60.7 s race) | frames p50 6.9 ms, p95 13.8 ms, max 62.5 ms; 1 frame > 50 ms; 0 long tasks; 2 window requests (2 s step, ~475 kB, 44–58 ms), 0 exact requests | `scripts/bench_playback.mjs`, headless Chrome 153, 1440 px |
| playback 64× (rate switched mid-play), 2.5 s (160 s race) | p50 7.0, p95 20.8, max 62.4 ms; 2 frames > 50 ms; 0 long tasks; 2 windows (4 s step, ~242 kB) | same |
| playback 1× / 4×, 2.5 s each | p95 7.1 / 7.1 ms; 1 window each (0.5 s step 933 kB, 149 ms; 1 s step 939 kB, 116 ms) | same |
| shown state vs cursor during all runs | never after the cursor, never back in time; lag ≤ one step (1.9 s at 16×, 3.9 s at 64×); 20 markers throughout; no error | sampled every 100 ms |
| pause, then step back two frames | paused: exact state = cursor; right after stepping back: no markers ("loading positions"); 0.8 s later: exact state = cursor | same |

## 9. Tests

New tests (functions added since the 12B spec commit):

| suite | new | covers |
|---|---:|---|
| `test_track_geometry.py` | 1 | `subpath` forward, across the line, closing vertex once |
| `test_spatial_contract.py` | 4 + 11 tamper cases | sectors on validated tracks only, lengths, endpoints, order; sector iff fraction; window equals state_at |
| `test_spatial_state.py` | 2 | sector at 0.25 / 0.42 / 0.75 of the lap; no fraction, no sector |
| `test_spatial_store.py` | 2 | old-shape caches rebuilt; line fractions round-trip |
| `test_spatial_api.py` | 4 | window route: equality with `?at=`, limits, 404/409, not shadowed by `/spatial/{driver}` |
| `test_spatial_real.py` | 3 | real sectors, real sector against distance at 50 times, real window = state_at |
| `tests/command/model.test.ts` | 14 | race-time reducer, frame derivation, ts filtering, `?t=`, formatting |
| `tests/command/command.test.tsx` | 13 | `?t=`, Shift+arrows, "as of" labels, map integration and map states |
| `tests/spatial/api.test.ts` | 12 | fail-closed client, 409 reasons, window plan |
| `tests/spatial/useSpatial.test.tsx` | 13 | debounce, latest wins, session change, playback windows, play start |
| `tests/spatial/trackmap.test.tsx` | 24 | renderer, states, keyboard, words, no browser computation (source scan) |
| `tests/spatial/geometry.test.ts` | 9 | fit, orientation, label placement |

**Final review (fresh reviewer, whole branch):** "with fixes". One Critical
(after playback every paused exact request failed: fractional `t` against the
millisecond echo) and three Important findings (a request storm after a
window failure, a state after the cursor shown, every panel re-rendered per
tick) plus four minors re-graded to Important (rate change jumping back, a
live session requesting `/track`, untimed frames refusing the page, a wrong
STALE definition) were fixed test-first in one pass (8 new tests, each red
first). Deferred minors and rulings are in the ledger and the final report.

**Mutations (frontend, each alone):** 18 of 18 killed - frame derivation off
by one, lists ignoring `ts`, session / track_id / request-time mismatch
accepted, unvalidated track drawn (renderer and client), STALE styled as
fresh, a state after the cursor used, the tick cap ignored, windows
re-requested in flight, `?t=` ignored, Shift+→ dropped, latest-wins removed,
debounce removed, NO_COVERAGE drawn, colour by status, y drawn downward.
Two first survived; their killing tests were added.

## 10. Limitations

- Positions are the backend's states on a grid while playing (up to one step
  of race time behind the cursor, labelled); an exact state when paused.
- A map sector is geometric (against the measured S1/S2 lines, p95 12–18 m
  on the Dutch GP); a car that close to a line can be in a different sector
  than official timing says.
- Only the Dutch GP race is validated; other sessions show the map only
  once their geometry passes the 12A gate with a cited lap length.
- Live sessions are not spatialized (12A is recording-only).
- Out of scope, unchanged: telemetry ↔ map sync (12C), battle geometry and a
  pit-lane path (12D), corners, apexes, DRS zones, racing lines.
