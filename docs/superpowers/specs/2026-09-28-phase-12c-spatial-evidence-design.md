# Phase 12C — Spatial evidence and telemetry at the cursor (design)

Status: design approved in conversation 2026-09-28 ("Approve as is"). This
document awaits review. Branch: `phase-12-spatial-intelligence` (12A and 12B
are complete there).

12C answers two questions:
- Where on the track was time gained or lost?
- What was the car doing there, at the one cursor?

It adds no new analysis. It connects three existing engines:
- evidence_v1 (10.5);
- the 12A spatial state;
- the car telemetry already in the recordings.

It stays inside the rules:
- raw samples only;
- nothing interpolated into a value that was not measured;
- normalized distance is never treated as a track position;
- the browser computes nothing.

Roadmap after 12C, agreed in conversation, each with its own spec:
race-craft on the map → 2026 energy and speed → qualifying mode →
validated projections → team radio at the cursor → season explorer →
production hardening.

## 1. Why the recording, not the database

The evidence, laps and telemetry routes read Postgres today. The only
validated track, the 2026 Dutch GP, lives in its recording, and the dev
databases were in `--rm` containers (Postgres is down on this machine).

Decision (approach A): **recording-backed sources**.
- Laps and car telemetry are read from the session recording through the
  same canonical models (`Lap`, `TelemetryCarSample`).
- They are identity-guarded, cached next to the recording like the spatial
  index, and fed to the unchanged engines.

Rejected:
- **B, reseeding Postgres from the recording.** It depends on Docker and
  duplicates the data.
- **C, frontend composition.** The browser would compute positions.

## 2. Source selection (backend)

| rule | behaviour |
|---|---|
| a recording exists for the session (`index_recordings`) | the **recording** is the source (the replay source of truth, as for the timeline and spatial routes) |
| no recording, session stored in the DB | the **database** is the source (e.g. the Singapore 10.x pair) |
| neither | 404 |

- Each response states its source in the header `X-Data-Source: recording | database`.
- Evidence bodies do not carry the source. For the same canonical rows and
  versions, both sources give **byte-identical** evidence (tested).

## 3. Recording stores (backend)

**`CarTelemetryStore`**, next to the recording:
- Files: `telemetry_car_v1.bin` + `.key`.
- Key: `car-index-1.0.0 | recording size | mtime_ns`.
- Content: per driver, time-sorted arrays `t`, `rpm`, `speed_kph`, `gear`,
  `throttle_pct`, `brake_pct`, `drs`.
- **Nulls are preserved:** NaN or −1 sentinels are written, and `None` is
  read back. Nothing is filled.
- Rows pass the existing identity guard (session and driver).
- Any read error, truncation or key mismatch triggers a rebuild, never a
  serve.

**`RecordingLapSource`:** the recording's `Lap` models, the `Driver`
identities, and the recording's `SessionInfo`.
- `deleted` comes from `LapCorrection` records when present; otherwise it
  is `null` ("not recorded"), never `false`.
- `has_car_telemetry` means at least one car sample inside the lap window.

## 4. Routes

| route | change |
|---|---|
| `GET /sessions` | also lists **recorded** sessions (from recording metadata) that are not stored, flagged `source: recording`; works with the DB down (`stored_error` stays as today) |
| `GET /sessions/{sid}/laps` | recording source when present; same body shape; `deleted` may be `null` |
| `GET /sessions/{sid}/telemetry/{driver}?start&end&frequency&fields` | recording source when present; same body shape; RAW keeps every sample; the 20 min RAW cap stays |
| `GET /sessions/{sid}/evidence/lap-comparison` | recording source when present; body unchanged (evidence_v1) |
| **new** `GET /sessions/{sid}/evidence/lap-comparison/spatial` (same query) | `evidence_spatial_v1` (§5) |

- Rate limiting is unchanged. The failure codes stay those of the existing
  routes: 404 / 409 / 422 / 500.
- A lap without a duration is still refused (422), and no window is ever
  guessed. The legacy `?lap=` 3-minute guess in the telemetry route is not
  reachable from the recording source: it returns 422 instead.

## 5. `evidence_spatial_v1` (placement by time)

For one evidence_v1 document, each segment's extent **for each driver** is
placed on the validated track:
1. Take the segment's own `provenance.ts_range_a` / `ts_range_b`: the first
   and last real samples of that driver inside the segment.
2. Read the 12A state of that driver at those two timestamps.
3. When both are `POSITIONED` on the reference with a fraction, the extent
   runs forward from the first fraction to the second.

| field | meaning |
|---|---|
| `contract_version`, `builder_version`, `evidence_id`, `track_id`, `session_id` | identity; `evidence_id` equals the evidence it places |
| `segments[]` | one per evidence segment, same `segment_id` and `label`, in order |
| `segments[].a` / `.b` | `status` (PLACED \| NOT_PLACED), `reason`, `from_ts`, `to_ts`, `from_fraction`, `to_fraction`, `polyline`, `from_xy`, `to_xy` |
| `line_placement_p95_m` | the 12A measured placement precision (m) |
| `limitations[]` | `SEGMENT_PLACED_BY_TIME`, `EVIDENCE_DISTANCE_NORMALIZED_NOT_POSITION`, `CORNER_PRECISION_NOT_MET` (when 12A's corner gate failed), `EXTENT_IS_SAMPLE_BOUNDED` |

Rules (the validator enforces them):
- A NO_DATA segment gets NOT_PLACED with reason `NO_TELEMETRY`.
- A time outside coverage, off the reference or without a fraction gets
  NOT_PLACED with that reason. No fraction is ever derived.
- The polyline is `Centerline.subpath` between the two fractions, and its
  endpoints equal `from_xy` / `to_xy`.
- The segments and their ids match the evidence exactly; fractions lie in
  [0, 1).
- An unvalidated track gives 409 with the gate's reasons.
- A session without a recording, or without spatial data, gives 404.

## 6. Command center: car telemetry at the cursor

A **Car telemetry** panel for the selected driver, in its own grid area
(`telemetry`) directly below driver focus. On phones it sits on the Timing
tab, under driver focus. It shows:
- speed (kph), throttle (%), brake (0/100 as delivered), gear and RPM;
- DRS as "not in this data" whenever every sample in the window is null.

Only samples **at or before the cursor** are shown, and the cursor sits at
the right edge:
- samples are drawn as markers joined by lines;
- a gap over 2 s between samples breaks the line and is labelled.

Data:
- Paused: the RAW telemetry route for `[t − 60 s, t + 60 s]`, debounced
  120 ms, latest request wins.
- Playing: the same window, prefetched ahead like the spatial windows.

In both cases the panel **selects** samples ≤ t. The window reaches past t
only so that playback has data ready; nothing after t is ever drawn.

**Map ghost.**
- Hovering or focusing a telemetry sample at time τ puts a hollow ghost
  ring on the map at that driver's own location sample at or before τ
  (within 2 s), from `/spatial/{driver}?from&to` over the same window.
- It is labelled "#NN at hh:mm:ss.s (hovered)".
- If there is no such sample, there is no ghost and the tooltip says why.

States: loading, ready, unavailable (no car telemetry / live / no recording),
error with retry. No driver selected: "Select a driver to see car
telemetry".

## 7. Evidence Workbench on the map

**Pickers.** Session → driver → lap, from the laps catalog; only laps with a
duration and car telemetry can be picked. The lap length is prefilled from
the track document's cited circuit length and its source, when the track is
validated. Otherwise the field stays empty and required, as today.

**Track context panel.** Shown when the session has a validated track.
- The selected segment's two extents are drawn on the map: driver A solid
  and driver B dashed, in the evidence colours plus A/B monograms.
- Every other placed segment appears as a faint tick at its start.
- Clicking a segment on the map selects it (the same URL state `seg`).
- NOT_PLACED extents are listed with their reason.
- The panel says: "extents placed by each driver's own sample times - not
  by the normalized distance axis".
- Without a validated track it shows "Track context unavailable" plus the
  reason, and no map.

**Link.** Driver focus → "Compare laps" opens `/evidence` with the session,
the focused driver and their last completed lap prefilled.

## 8. Frontend units

| unit | role |
|---|---|
| `src/telemetry/api.ts`, `types.ts` | fail-closed client for the telemetry route (session, driver, window echo, `X-Data-Source`) |
| `src/telemetry/useTelemetryWindow.ts` | window selection for the cursor (debounce, latest wins, prefetch) - pattern of `useSpatial` |
| `src/components/telemetry/CarTelemetryPanel.tsx` | channels up to the cursor, hover → ghost |
| `src/evidence/spatial.ts` | fail-closed client for `evidence_spatial_v1` |
| `src/components/evidence/TrackContext.tsx` | the workbench map, reusing `components/spatial/geometry` and `MapLayers` |
| `src/components/evidence/LapPickers.tsx` | session / driver / lap pickers from the laps catalog |
| TrackMap | new optional prop `ghost: {driver, at, x, y} \| null` |

## 9. Accessibility and motion

- Telemetry channels have a hidden table; the selected sample is announced.
- Keyboard: ←/→ move the hovered sample; Esc clears the ghost.
- On the workbench map, segment extents are buttons named "R09, #55 lap 19,
  placed by time".
- No new motion beyond the existing reduced-motion rules.

## 10. Performance (measured, never claimed)

To measure:
- car index cold build and warm load;
- RAW telemetry window of 120 s: bytes and latency;
- the evidence route from the recording;
- the `evidence_spatial_v1` route;
- the command-center frame budget while playing with the telemetry panel
  open (`scripts/bench_playback.mjs` extended).

## 11. Testing

**Backend** (TDD; synthetic plus real):
- the store: nulls round-trip, key, corruption rebuild, identity;
- source selection and the `X-Data-Source` header;
- recording-source evidence equals DB-source evidence byte for byte
  (synthetic DB when Postgres is up; skipped otherwise, with the reason);
- the real Dutch GP pair evidence builds and validates;
- `evidence_spatial_v1`: placement at each segment's own sample times
  equals `state_at`; NOT_PLACED reasons; polylines' endpoints; tamper
  cases; 409 / 404.

**Frontend:**
- samples never after the cursor;
- gaps labelled;
- DRS shown as unavailable;
- ghost at the sample's own position;
- fail closed on another session, driver or window;
- pickers only offer laps with a duration and telemetry;
- lap length prefilled with its citation;
- the track context draws only PLACED extents;
- workbench URL state survives.

**Mutations (each must be caught):**
- a sample after the cursor drawn;
- a gap bridged;
- a null drawn as 0;
- a ghost from another driver or a later sample;
- evidence and spatial from different evidence_ids accepted;
- a NOT_PLACED extent drawn;
- recording rows not identity-guarded;
- a deleted `null` shown as `false`.

**Browser QA:** 375 / 768 / 1024 / 1440 / 1920 px on the real Dutch GP, plus
the headless playback benchmark.

## 12. Documentation

- `docs/PHASE_12C_SPATIAL_EVIDENCE.md`;
- MASTER.md §15;
- updates to the RaceWise contract document (the new `X-Data-Source`
  header; evidence_v1 is unchanged);
- the CLAUDE.md handoff.

## 13. Out of scope

- Overtakes, pit cycles, battles on the map, pit-lane path (race-craft).
- Speed traps and energy (next).
- Corners, apexes, DRS zones, racing lines.
- Mini-sector maps: their boundaries are not in the data.
- Live spatial.
- RaceWise, AI, prediction.
