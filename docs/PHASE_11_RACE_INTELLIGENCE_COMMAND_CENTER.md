# Phase 11 — Race Intelligence Command Center

The command center answers "what is happening across this session, what
happened, and where should I look?". Every panel shows **one session
moment**, chosen by a single cursor over backend-computed lap frames. The
browser selects, orders and formats; it computes no gap, position, battle,
stint or strategy.

- Route `/` (and `/sessions` for discovery). The Evidence Workbench stays at
  `/evidence`; the legacy live pit wall moved to `/pitwall`.
- Design source: `design-system/live-f1-intelligence/MASTER.md` §13 plus
  `pages/command-center.md`.
- Real data: the 2026 Dutch GP race (OpenF1 session 11353), which includes a
  lap-2 red flag (13:05–13:33 UTC) and two VSC periods.

## 1. Architecture

```
recording (canonical envelopes, replay source of truth)
  -> order_for_replay (race order)          app/analysis/timeline.py
  -> AnalysisEngine (the realtime hub's engine, unchanged in meaning)
  -> TimelineRecorder: START, each leader lap end, FINAL  -> session_timeline_v1
  -> GET /api/v1/sessions/{sid}/timeline   (cached next to the recording)
  -> buildMoment(timeline, cursor)          frontend/src/command/moment.ts
  -> every panel
```

A running hub captures the same frames live with the same `TimelineRecorder`
(`SessionHub.timeline`). For one race the hub's LAP frames equal the offline
build's (`test_timeline_api.py`).

### Why the recording is re-ordered

A historical OpenF1 backfill is recorded in fetch order: every lap first,
then telemetry windows, then pits, weather, race control, positions and
intervals, with stints carrying no timestamp. Folding that order gives a
correct final state but meaningless intermediate states. The effective
race-time rules (ties keep recording order):

| model | effective time |
|---|---|
| identity (session, team, driver) | before everything |
| Lap | completion (`started_at + duration_s`); its start if it has no duration |
| SectorTime | its lap's completion |
| TyreStint | `lap_start <= 1` before the start; else the driver's lap-`lap_start` start |
| everything else | its source timestamp |

The existing streamed replay (`ReplayProvider` over a hub) still plays a
recording in file order and cannot seek. For backfilled recordings the lap
timeline is the authoritative replay; this is noted under limitations.

## 2. `session_timeline_v1`

Built by `build_timeline` / `TimelineRecorder.to_dict`, validated by
`validate_timeline` (fail closed), serialized canonically (sorted keys, NaN
refused). Builder `timeline-builder-1.0.1`; engine `analysis-2.0.0`.

| field | meaning |
|---|---|
| `frames[]` | `START` (earliest lap-1 start), `LAP k` (the moment the leader completes lap k), `FINAL` |
| `frames[].rows[]` | the engine leaderboard + `position_change` (vs previous frame), `pit_stops`, `stint_laps_completed`, `tyre_age_at_start`, `tyre_laps_on_set`, `sectors_last` |
| `frames[].active_battles` | BattleDetector pairs that are neighbours at that moment |
| `stints`, `pit_stops`, `race_control`, `weather`, `events` | observed lists; each item carries `frame_index` = the first frame that includes it |
| `pit_stops[].compound_before/after` | joined from stint records (`after` only when a stint starts on the next lap) |
| `capabilities` | what the data cannot provide: DRS availability, undercut/overcut, track geometry, retirement status, scheduled distance |
| `limitations[]` | coded, e.g. `FRAME_AT_LEADER_LAP_END`, `LATEST_SAMPLE_AT_FRAME`, `RACE_ORDER_RECONSTRUCTED` |

Golden: `docs/timeline/session_timeline_v1_dutch_gp_2026.json` (1.3 MB,
~97 KB gzipped), regenerated with `scripts/timeline_report.py`, locked by
`test_real_build_matches_the_committed_golden`.

## 3. API

| route | notes |
|---|---|
| `GET /api/v1/sessions` | `active` (unchanged) + `stored` (DB sessions: metadata as stored, driver/lap counts, telemetry present, timeline available). Works without a realtime registry; `stored_error` if the DB is down |
| `GET /api/v1/sessions/{sid}/laps` | drivers (identity as stored, else null) and laps, each with `has_car_telemetry` inside the lap window |
| `GET /api/v1/sessions/{sid}/timeline` | hub capture if running, else the recording's cached timeline; identity-checked; 404 / 500 fail closed |

No migration: queries use session-level rows, the laps PK/index and one
`EXISTS` probe on the telemetry index.

## 4. Engine defects found on real data (fixed, test first)

| defect (real symptom) | fix |
|---|---|
| `in_pit` never cleared: after a first stop every car showed PIT for the rest of the race and was excluded from battles | cleared when the out-lap completes |
| 84 "active battles" for 22 cars at lap 40; stale pairs never expired; cars without a position counted as P0 | pairs end when cars stop being neighbours; the snapshot checks adjacency |
| the lap-2 red flag was ended the same second by "CLEAR IN TRACK SECTOR 16" | clears never end a red flag; `SESSION STARTED` resumes (OpenF1 `SessionStatus` maps to category UNKNOWN) |
| the leader had no position for 36 minutes: the starting grid is published 53 min before the start, outside the 45-min backfill seed | session-keyed channels start 3 h before |
| sector status re-derived later against a moved session best | `SectorEngine.last_class` keeps the status at crossing time |

## 5. Frontend

`src/command/`: `types.ts` (contract mirror), `api.ts` (fail closed:
contract, session identity, frame order), `moment.ts` (the one moment),
`state.ts` (cursor, playback, selection, URL `?session&lap&driver`),
`format.ts` (formatting and vocabulary only), `useResource.ts`.

`src/components/command/`:

| panel | shows (all at the cursor) |
|---|---|
| Timing | backend order, gap/interval (symbolic gaps verbatim), lap, last/best (PB/FL markers), last sector crossings, tyre + laps on set, stops, PIT |
| Position evolution | positions per lap frame up to the cursor, P1 top, gaps = not reported, red/VSC bands |
| Battles | detector pairs; gap dominant; selected pair's measured interval while neighbours; DRS stated unavailable |
| Driver focus | the row, stints so far, pit stops, battles, lap-comparison entry into `/evidence` (laps with a time and telemetry only) |
| Tyres & strategy | observed stints clipped at the cursor, pit ticks, pit list with compounds either side; no strategy inference |
| Race control | official messages verbatim (key / flags / incidents / all) and derived session events; selecting one moves the cursor |
| Weather | the frame's latest reading; track/air trace of samples so far |
| Replay bar | start / previous / play / next / end, phase-segmented scrubber (`input[type=range]`), speed in laps per second |

Mode is always visible: `HISTORICAL` for recordings, `REPLAY` when the cursor
is before the end, `LIVE` only for a connected hub.

## 6. Replay

The replay clock is a cursor over the lap frames. Play advances one frame
per tick at 1, 2, 5 or 10 laps per second (labelled as such, never as race
time). Seek, scrub, step, jump to start/end, jump to a race-control message
or pit stop, and deep links (`?lap=42`) all set the same cursor. There is no
second clock.

## 7. Responsive and accessibility

Verified in the browser on the real timeline at 375, 768, 1024, 1440 and
1920 px with no horizontal page overflow.
- ≥ 1440: timing | chart + battles | focus; strategy | race control + weather.
- 1024–1439: two columns. 768–1023: one column. < 760: recomposed into
  Timing / Race / Strategy / Events tabs with a moving indicator.
- Keyboard: Space/K play, ←/→ step, Home/End, ↑/↓ in the tower, Enter
  select, Esc clear, `?` help. Skip link, visible focus, real buttons,
  `aria-pressed`, `aria-live` readout, hidden table behind the chart.
- `prefers-reduced-motion` removes the row glide, ticks and shimmer.

## 8. Tests

| suite | count | covers |
|---|---:|---|
| `test_engine_pit_state.py` | 6 | pit state |
| `test_engine_battle_adjacency.py` | 5 | battle adjacency (3 mechanisms mutation-checked) |
| `test_provider_contract.py` (changed) | +2 | red flag on the real message sequence |
| `test_openf1_backfill_window.py` | 2 | starting grid inside the backfill |
| `test_session_timeline.py` | 28 | ordering, frames, no future leakage, validation (10/10 builder mutations) |
| `test_session_timeline_real.py` | 11 | every frame vs values recomputed from raw rows; golden |
| `test_timeline_api.py` / `test_discovery_api.py` | 6 / 5 | routes; hub frames = offline frames |
| `frontend/tests/command/` | 37 | one session state at laps 10/20/30, tampering, no fabrication, spatial safety, keyboard, fail closed (7/7 mutations) |

## 9. Limitations

- Frames are leader-lap boundaries: other cars are mid-lap, and values are
  the latest samples (a gap can lag a position change by seconds).
- The scheduled race distance, retirement status, DRS availability and
  undercut/overcut are not in the data; the UI says so.
- LIVE is implemented through the hub's timeline capture but was not
  verified against a live session (OpenF1 live access needs a sponsor
  token). Between lap frames a live view shows the last captured frame.
- The Dutch GP recording was finalized after the recorder stalled on an
  HTTP 429 (post-race telemetry windows missing; race data complete; see
  `meta.json` `interrupted`).
- Only a race recording was available. For qualifying/practice the builder
  would still frame the first completion of each lap number, which has no
  race meaning there; session-type-specific frames and layouts are future
  work and are unverified.

## 10. Future

- **Spatial intelligence:** validated circuit centerline, physical car
  position, corner mapping, spatial battles. Not attempted: normalized
  distance is never shown as track position.
- **Prediction:** pace and degradation projection, strategy scenarios,
  pit windows. Not implemented; the backend's predictive strategy
  candidates are not shown.
- **AI:** none added; the timeline is a clean input for a future layer.
