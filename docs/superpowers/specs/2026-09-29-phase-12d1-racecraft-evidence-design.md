# Phase 12D-1 — Race-craft evidence on the map (design)

Status: design approved in conversation 2026-09-29 ("go on"). This document
awaits review. Branch: `phase-12-spatial-intelligence` (12A-12C complete).

12D-1 answers three questions, observationally:
- Where on the track did each position change happen, and in what measured
  context (both cars on the line, one in the pit lane, no coverage)?
- What did a pit stop do to the driver's order and gaps, before versus after?
- Which pairs are battling at the cursor, and where are they?

It adds no cause, no "clean pass", no "undercut worked", no prediction.
Every value is a provider row, a latest sample with its own time, or a 12A
spatial state at the value's own instant.

12D-2 (pit-lane geometry measured from observed traversals, behind its own
gate) follows with its own spec; nothing here depends on it.

## 1. Measured facts that shape the design (2026 Dutch GP, OpenF1 11353)

- OpenF1 `/overtakes` (docs: races only, "may be incomplete", includes
  "position changes resulting from pit stops or post-race penalties"):
  **292 rows**, 13:03:37.490 to 15:03:49.106 UTC.
  - Fields: `date`, `session_key`, `meeting_key`,
    `overtaking_driver_number`, `overtaken_driver_number`, `position` (the
    overtaking driver's position after).
  - One move can give several rows at the same instant, one per car passed.
- The recording has no overtake rows. It does have 608 `PositionUpdate`,
  65 `PitStop` and 30,616 `TimingInterval` rows.
- **All 292** overtakes coincide exactly (to the millisecond) with a
  recorded position row of the overtaking driver. At that instant the
  recorded position feed agrees with the row for **259**; for the other
  **33** it does not. They are classified per overtake (§4) and never
  hidden.
- 12A: `PitStop.ts` is the pit **exit** on this session; `lane_duration_s`
  is the time in the pit lane.

## 2. Overtakes as a new source (OpenF1, sidecar next to the recording)

The recording is the replay source of truth, but it holds no overtakes.
Rejected: deriving swaps ourselves from `PositionUpdate`. That would be a
second overtake engine, and the provider already publishes them. The
position feed is used as an independent **check** instead (§4).

- **Fetch:** `scripts/fetch_overtakes.py --session-key 11353 --recording
  <dir>` does one GET of `/v1/overtakes?session_key=`.
  - During a live window a 401 is reported and never retried in a loop.
  - It writes `openf1_overtakes_v1.json` next to the recording:
    `{provider, endpoint, params, retrieved_at, row_count, sha256, rows}`.
    The rows are verbatim; `sha256` is over the canonical JSON of `rows`.
- **Identity** (fail closed), a new `validate_session_rows(rows, *,
  session_key)` in `app/providers/openf1/real_data.py`:
  - every row carries exactly the session key;
  - both driver numbers are integers and differ.

  The loader also requires both drivers to be drivers of the recorded
  session. One bad row fails the file.
- **Canonical model** `Overtake` (`app/core/models.py`): `session_id, ts,
  overtaking_driver_number, overtaken_driver_number, position_after,
  provenance` (class B). Mapper `to_overtake(row, session_id)` in
  `app/providers/openf1/mapping.py`.
- **Test fixture:** a copy of the real rows is committed at
  `scripts/fixtures/openf1-11353-overtakes/overtakes.json` (public data,
  about 50 kB) with its `meta.json`.
- **Without the sidecar:** overtakes are *unavailable* with the reason
  `OVERTAKES_NOT_FETCHED`. Nothing is derived in their place.

## 3. `racecraft_v1` (backend, `app/racecraft/`)

One document per recorded session, cached next to the recording:
`racecraft_v1.json` plus a `.key`. The key is `racecraft-builder-1.0.0 |
recording size | mtime_ns | overtakes sha256 or "none" | 12A track_id or
"none"`. A mismatch rebuilds, never serves.

| field | meaning |
|---|---|
| `contract_version`, `builder_version`, `session_id`, `track_id` (or null) | identity |
| `capabilities.overtakes` | `{available, reason}`; reason `OVERTAKES_NOT_FETCHED` or null |
| `overtakes[]` | §4, in time order (ties: overtaking, then overtaken driver number) |
| `pit_stops[]` | §5, in time order |
| `limitations[]` | `{code, message}` (§7) |
| `provenance` | chain, `input_digest` (sha256 over the canonical overtakes, pit stops, position and interval rows used), overtakes `sha256` and `retrieved_at`, counts |

`frame_index` on every item is the first Phase 11 timeline frame whose
time is at or after the item's time (the item first appears there), or
`null` after the last frame. It is the same rule as the timeline's lists.

## 4. Overtakes

| field | meaning |
|---|---|
| `id` | `ot_` + the first 16 hex characters of sha256(`ts`, overtaking, overtaken) |
| `ts`, `overtaking`, `overtaken`, `position_after` | the provider row (class B) |
| `frame_index` | §3 |
| `state_overtaking`, `state_overtaken` | the 12A `driver_state` of each car at `ts`, verbatim (status, flag, x/y, fraction, sector, lap, confidence, bracket); null when the track is unvalidated |
| `context` | the measured context of the pair at `ts` (below) |
| `position_check` | the independent check against the recorded position feed (below) |
| `xy` | the overtaking car's x/y at `ts` when its state is POSITIONED; else null (not drawn) |

**`context`** is the first that applies:
1. `SPATIAL_UNVALIDATED`: no validated track;
2. `NO_COVERAGE`: either car has no location coverage;
3. `STALE`: either state is stale;
4. `PIT_LANE_INVOLVED`: either car is in the pit lane;
5. `OFF_REFERENCE_INVOLVED`: either car is off the reference;
6. `BOTH_ON_REFERENCE`.

These are states, never judgements: `BOTH_ON_REFERENCE` is not "an
on-track pass".

**`position_check`** uses the recorded `PositionUpdate` rows: the latest
row at or before a time, per driver.

| code | when | extra field |
|---|---|---|
| `CONSISTENT_AT_TS` | at `ts` the overtaking driver's position = `position_after` and the overtaken driver's position is greater | — |
| `OVERTAKEN_BEHIND_LATER` | the overtaking position matches at `ts`, the overtaken car is not yet behind, and its first later row places it behind | `delay_s` (measured, no threshold) |
| `POSITION_MISMATCH` | the overtaking position at `ts` ≠ `position_after`, or the overtaken car is never placed behind | — |
| `NOT_CHECKABLE` | either driver has no position row at or before `ts` | — |

## 5. Pit stops (observed, before versus after)

Per recorded `PitStop` (65 on the Dutch GP):

| field | meaning |
|---|---|
| `id` | `ps_` + hash(driver, exit_ts) |
| `driver`, `lap_number`, `stop_duration_s`, `lane_duration_s` | provider values (class B) |
| `exit_ts` | `PitStop.ts` (the exit on this session, 12A) |
| `entry_ts` | `exit_ts − lane_duration_s` (class C); null with `LANE_DURATION_MISSING` when the lane time is null |
| `out_lap` | the driver's lap row with `started_at ≤ exit_ts < started_at + duration_s`; its number and completion time, or null (`NO_OUT_LAP`: retired, or the lap has no duration) |
| `at_entry`, `at_exit`, `at_out_lap_end` | each: `{t, position, position_ts, interval_s, gap_to_leader_s, gap_raw, interval_ts}`. The latest `PositionUpdate` and `TimingInterval` of the driver at or before `t`, with their own times; null values where no row exists |
| `position_change` | `at_out_lap_end.position − at_entry.position` (class C; negative = moved up); null unless both exist |
| `overtakes_during` | ids of overtakes with `ts` in `[entry_ts, exit_ts]` involving the driver, either role |
| `frame_index` | §3, by `exit_ts` |

No field says why the order changed.

## 6. API

`GET /api/v1/sessions/{sid}/racecraft` returns `racecraft_v1`:
- canonical bytes, header `X-Racecraft-Contract: racecraft_v1`;
- 404 without a recording;
- 500 withheld (contract or identity failure; also a sidecar whose
  `sha256` or identity check fails);
- 200 with `capabilities.overtakes.available = false` when no sidecar
  exists;
- 200 with `track_id: null` and context `SPATIAL_UNVALIDATED` when the
  track is not validated.

The first request builds the document (it reuses the recording store, the
spatial index and the timeline caches), then it is served from cache.

## 7. Limitations (codes)

| code | meaning |
|---|---|
| `OVERTAKES_PROVIDER_DEFINED` | rows are OpenF1's; they include position changes from pit stops and post-race penalties and "may be incomplete" (provider documentation) |
| `CONTEXT_IS_STATE_NOT_CAUSE` | context codes describe measured states at the instant, not how or why the order changed |
| `POSITIONS_ARE_LATEST_SAMPLES` | positions and intervals are the latest rows at or before a time, each with its own time |
| `PIT_ENTRY_FROM_LANE_DURATION` | pit entry is exit minus the provider's lane time, not an observed crossing |
| `INTERPOLATED_BETWEEN_SAMPLES` | 12A: positions at an instant lie between two samples of that car |
| `CORNER_PRECISION_NOT_MET` | when 12A's corner gate failed (Dutch GP) |

The contract validator rejects:
- items out of time order;
- a `frame_index` out of range;
- an `xy` without a POSITIONED overtaking state;
- a context that disagrees with the two states;
- a `position_check` code without its required fields;
- `overtakes_during` naming an unknown id;
- a `position_change` that is not the difference of its two positions;
- unknown fields;
- overtakes present while `available = false`.

## 8. Frontend

`src/racecraft/{types,api,useRacecraft}.ts`: the document is loaded once
per session. It fails closed on the contract header and body, the session,
and a track that is not the loaded 12B track.

**Map (TrackMap, new optional props).**
- **Overtakes:** those with `ts` in `(t − 60 s, t]` and an `xy` are drawn
  as a small hollow diamond at the overtaking car's own position at that
  instant.
  - Label on hover or focus: "#16 passed #44 → P5 · 14:03:37.8".
  - A tag when `context` is `PIT_LANE_INVOLVED` ("pit lane") or
    `OFF_REFERENCE_INVOLVED` ("off line").
  - Nothing after the cursor is drawn.
- **Battles:** every active battle of the current timeline frame gets a
  dashed link between the two markers. This is selection from the
  timeline only; the selected battle keeps its 12B emphasis.

**Race-craft panel** (grid area `racecraft`; the Events tab on phones):
- **Overtakes up to the cursor**, newest first.
  - Filters: all / both on the reference / the selected driver.
  - Each row: time, the two cars, position after, context in words, the
    position check in words (with the measured delay when later).
  - Selecting a row moves the cursor to its time.
- **Selected driver's pit stops up to the cursor.**
  - Each row shows entry, exit and out-lap end: position and interval,
    each with its own time.
  - Also: the position change, and the overtakes during the stop.
  - Selecting a row moves the cursor to the exit.
- **States:** loading; overtakes unavailable (reason); a session without
  overtakes; error with Retry.

**Vocabulary:** a test forbids causal words ("because", "undercut",
"overcut", "clean", "better", "gained by", "lost by") in racecraft source
and output strings.

## 9. Accessibility and motion

- Overtake markers are buttons named like the label.
- The panel is a list of buttons, plus a hidden table of every overtake up
  to the cursor.
- No new motion beyond the existing reduced-motion rules.

## 10. Performance (measured, never claimed)

To measure:
- `racecraft_v1` cold build and warm load;
- the document size;
- a playback frame budget with the race-craft layer and panel open
  (`scripts/bench_playback.mjs`).

## 11. Testing

**Backend** (TDD; synthetic plus real):
- the sidecar: sha256, identity (another session, a driver outside the
  session, equal drivers), missing file;
- the mapper;
- `position_check`: each code, the delay, and the recorded-feed edge cases;
- `context`: each code, and the ordering;
- pit stops: entry, the out-lap choice, latest samples with their times,
  the position change, overtakes during the stop, a null lane time, no
  out-lap;
- `frame_index`;
- contract tamper cases;
- the route: 200 / 404 / 500, unavailable, unvalidated;
- the cache key and rebuild.

**Real (skips without the recording or fixture):**
- 292 overtakes;
- 259 `CONSISTENT_AT_TS`;
- every other `position_check` recomputed from the raw position rows;
- contexts recomputed from `state_at`;
- 65 pit stops with values recomputed from the raw rows.

**Frontend:**
- the fail-closed client;
- overtakes only in `(t − 60 s, t]`, none after the cursor;
- no marker without `xy`;
- battle links only for active pairs;
- panel filters and seeking;
- the vocabulary;
- pit rows with their own sample times.

**Mutations (each must be caught):**
- an overtake after the cursor drawn;
- context computed from one car only;
- `position_check` ignoring the overtaken car;
- `OVERTAKEN_BEHIND_LATER` without a delay;
- the entry time taken as the exit;
- the out-lap chosen by lap number;
- the latest sample chosen after `t`;
- the sidecar sha check removed;
- the identity check removed;
- a battle link drawn for a non-active pair;
- `xy` placed for a stale state.

**Browser QA:** 375 / 768 / 1024 / 1440 / 1920 px on the real Dutch GP,
plus the headless playback benchmark.

## 12. Documentation

- `docs/PHASE_12D1_RACECRAFT.md`;
- MASTER.md §16;
- `docs/DATA_SOURCES.md` (`/overtakes` now used; facts from §1);
- the Phase 12 table;
- the CLAUDE.md handoff.

## 13. Out of scope

- Pit-lane geometry (12D-2).
- Spatial separation in metres between battling cars.
- Any classification of how a position changed.
- Qualifying and sprint sessions (no recording yet).
- Live sessions (recordings only).
- RaceWise, AI, prediction.
