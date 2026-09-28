# Phase 12C — Spatial evidence and car telemetry at the cursor

12C answers two questions without adding any analysis:
- Where on the track did an evidence segment run?
- What was the car doing there, at the one cursor?

It connects three existing engines:
- evidence_v1 (10.5);
- the 12A spatial state;
- the car telemetry already in the recordings.

Only raw samples are drawn, nothing is interpolated into a value that was
not measured, normalized distance is never treated as a track position,
and the browser computes nothing.

- Spec: `docs/superpowers/specs/2026-09-28-phase-12c-spatial-evidence-design.md`
- Plan: `docs/superpowers/plans/2026-09-28-phase-12c-spatial-evidence.md`
- Visual rules: `design-system/live-f1-intelligence/MASTER.md` §15

## 1. Architecture

```
recording ──► RecordingStore (laps, identities, raw car + location samples)   app/storage/recording_store.py
             ├► /laps, /telemetry/{driver}, /evidence/lap-comparison   (X-Data-Source: recording)
             └► evidence_v1 ──► place_evidence (12A driver_state at each
                                segment's own sample times)            app/spatial/evidence_spatial.py
                                └► /evidence/lap-comparison/spatial   (evidence_spatial_v1)
frontend:
  ui.t (THE cursor) ─► useTelemetryWindow ─► CarTelemetryPanel (samples ≤ t)
                     hovered sample τ ─► useGhost (/spatial/{driver} over [τ − 2 s, τ]) ─► TrackMap ghost
  /evidence ─► LapPickers (/sessions, /laps, /track) ─► useTrackContext (/track, …/spatial) ─► TrackContext
```

## 2. Recording-backed sources (approach A)

The only validated track, the 2026 Dutch GP, lives in its recording, and
Postgres is not running on this machine. Where a recording holds a session,
it is therefore the source. The database is used otherwise, and 404 is
returned when neither holds the session.

| route | recording source | header |
|---|---|---|
| `GET /sessions` | new `recorded[]` list, built from `meta.json` before any DB access; works with the DB down | — |
| `GET /sessions/{sid}/laps` | same body shape; `deleted` is true/false only from a `LapCorrection`, otherwise `null` | `X-Data-Source` |
| `GET /sessions/{sid}/telemetry/{driver}` | same body shape; RAW keeps every stored sample; a recorded lap without a duration is refused (422) and its window is never guessed; times need a UTC offset | `X-Data-Source` |
| `GET /sessions/{sid}/evidence/lap-comparison` | evidence_v1 unchanged | `X-Data-Source` |

**The store** (`recording-store-1.0.0`) keeps its caches next to the
recording:
- **Files:** `laps_v1.json`, `telemetry_v1.bin` (car and raw location
  arrays) and `recording_store_v1.key`. The key file is written last, so
  it marks both caches complete.
- **Identity:** every row passes the 12A identity guard.
- **Nulls:** they stay null. Ints use a sentinel and floats use NaN, and
  both read back as `None`.
- **Duplicates:** identical ones collapse; conflicting ones (the same
  instant with different values) are all dropped and counted.
- **Laps:** the later row wins.
- **Rebuilds:** a stale key, a truncated file or trailing bytes trigger a
  rebuild, never a serve.

**Same data, same bytes (measured).**
- The unmodified Singapore pair rows, written into a recording, make the
  route reproduce the committed `evidence_v1_singapore.json` byte for byte.
  That golden is also what the database route returns
  (`test_evidence_api`, `test_evidence_real`).
- The Dutch GP pair's `input_digest` equals the digest recomputed from an
  independent parse of the raw frames.

**Facts measured on the Dutch GP recording.**
- Rows: 900,900 car rows, 890,494 location rows and 7 later-wins lap
  duplicates. There are **0** identical and **0** conflicting car
  duplicates, so the database's first-row rule agrees on this data.
- `LapCorrection` #22 lap 43 has no Lap row; it is counted, and no lap is
  invented.
- DRS is null in every car sample (as 12A found).

## 3. `evidence_spatial_v1`

For one evidence_v1 document (same request), each segment's extent is
placed per driver:
1. Take the segment's own provenance `ts_range_a/b`: that driver's first and
   last real samples inside the segment.
2. Read the 12A `driver_state` at those two times.
3. If both ends are on the reference with a lap fraction, the extent runs
   forward along the reference: `Centerline.subpath`, with its end points
   equal to the states' x/y.

| field | meaning |
|---|---|
| `evidence_id`, `session_id`, `track_id`, `driver_a`, `driver_b` | identity; must equal the evidence it places |
| `segments[]` | the evidence's segments, same ids, labels and order |
| `segments[].a/.b` | `status` PLACED/NOT_PLACED, `reason`, `from_ts`/`to_ts` (the segment's own), fractions, `from_xy`/`to_xy`, `polyline` |
| `line_placement_p95_m` | 12A's measured timing-line placement precision |
| `limitations[]` | `SEGMENT_PLACED_BY_TIME`, `EVIDENCE_DISTANCE_NORMALIZED_NOT_POSITION`, `EXTENT_IS_SAMPLE_BOUNDED`, `INTERPOLATED_BETWEEN_SAMPLES`, and `CORNER_PRECISION_NOT_MET` when the corner gate failed |

**NOT_PLACED reasons** (the first applying, per end):
- `NO_TELEMETRY`: the segment is NO_DATA (even though evidence gives it a
  single-instant `ts_range`) or has no range;
- `NO_COVERAGE`, `STALE`, `PIT_LANE`, `OFF_REFERENCE`;
- `NO_FRACTION`: on the line, but the fraction was withheld.

The validator rejects:
- a document for another evidence, session or driver pair;
- reordered segments;
- a PLACED extent without fractions or a path;
- a NOT_PLACED extent with any position;
- a fraction outside [0, 1);
- a path whose ends are not `from_xy`/`to_xy`;
- times that are not the segment's own;
- unknown fields.

Route: `GET /sessions/{sid}/evidence/lap-comparison/spatial` (same query as
evidence). Headers: `X-Spatial-Contract`, `X-Evidence-Id`, `X-Data-Source`.
Status codes:
- 422 for a bad request;
- 404 without a recording;
- 409 while the track is unvalidated (with the gate's reasons);
- 500 withheld.

**Real result.** The Dutch GP pair was chosen by rule: the overall fastest
eligible lap, then another driver's fastest.
- The pair: #16 LEC lap 60 vs #81 PIA lap 61, lap delta −0.073 s.
- Of 11 segments, **4 are significant**. None were on the Singapore pair.
- All 10 covered segments are PLACED for both drivers. The NO_DATA tail is
  NOT_PLACED (`NO_TELEMETRY`).
- Every placed end equals `state_at` at its own time (test).

## 4. Command center: car telemetry at the cursor

What the panel shows (grid area `telemetry`, below driver focus; on the
Timing tab on phones):
- the selected car's stored samples in the 60 s up to the cursor: speed,
  throttle, brake (0/100 as delivered), gear and RPM;
- markers joined by lines, broken and labelled ("No samples a–b") wherever
  two samples are more than 2 s apart;
- "DRS: not in this data" when every sample in the window is null.

Nothing after the cursor is drawn. When the panel is narrower than 480 px,
each label and value sit on a line above a full-width plot.

**Windows.** `useTelemetryWindow` requests RAW `[t − 60 s, t + ahead]`.
- Paused: after a 120 ms debounce, with the latest request winning.
- Playing: fetched ahead as the cursor nears the end of the loaded window.
  The reach grows with the rate: 60 s at 1×, 120 s at 4×, 480 s at 16× and
  1,080 s at 64×. That is about one request per 15–30 s of wall time,
  always under the route's 20-minute RAW cap.
- Windows are tagged with their session and driver, so a driver change
  shows nothing old. A failure stops requests until Retry. Live sessions:
  unavailable.

**Ghost.** Hovering or stepping (←/→, Home/End, Esc) reports one stored
sample at its own time τ.
- `useGhost` requests that driver's `spatial_trace_v1` over `[τ − 2 s, τ]`.
- The map draws a dashed ring at the **last** location sample in that
  range, labelled "#NN at hh:mm:ss.s (hovered)".
- No sample in those 2 s means no ghost, and the readout says why.

## 5. Evidence Workbench on the map

**Pickers.** The pickers choose session, driver and lap.
- They load `/sessions`, `/laps` and `/track` only when opened.
- Recorded sessions work with the DB down.
- Only laps with a time and stored car telemetry are offered.
- The lap length and its citation are prefilled from a validated track's
  cited circuit length, into empty fields only.

**Track context** (side column, above the inspector):
- the selected segment's two PLACED extents, A solid and B dashed, with
  A/B monograms;
- a named button per placed segment ("R05, #16 lap 60, placed by time")
  that selects it (URL `seg`);
- every NOT_PLACED extent listed with its reason;
- the caption "placed by each driver's own sample times … not by the
  normalized distance axis".

Without a validated track (e.g. Singapore, which has no recording) it shows
"Track context unavailable" with the reason, and no placement is requested.

## 6. Performance (measured)

| measure | result | method |
|---|---:|---|
| recording store cold build | 85.1 s (900,900 car + 890,494 location rows), once per recording and store version | `scripts/evidence_fixture.py --measure` |
| recording store warm load | 0.27 s; caches 0.74 MB + 63.6 MB | same |
| `/laps` | median 84.9 ms, 206 kB | TestClient, median of 15 warm |
| telemetry RAW 120 s | median 37.7 ms, 128.6 kB | same |
| evidence_v1 from the recording | median 119.7 ms, 54.6 kB | same |
| evidence_spatial_v1 | median 143.0 ms, 18.2 kB | same |
| playback 16×, telemetry panel open | frames p50 13.9 / p95 20.9 / max 41.7 ms; 0 long tasks; 1 telemetry request (547 kB, 123 ms) per 60 s of race | `LFI_URL=…&driver=16 node scripts/bench_playback.mjs`, headless Chrome, 1440 px |
| playback 64×, panel open | p95 34.7 ms, 3 frames > 50 ms, one 56 ms long task; telemetry 1.19 MB per window | same |
| playback 1× / 4×, panel open | p95 14.0 / 14.1 ms | same |
| `/sessions` with Postgres down | ~4.1 s (the refused localhost connection); pre-existing Phase 11 behaviour, not changed | browser |

12B without the panel measured a 16× p95 of 13.8 ms, so the panel costs
about 7 ms per frame at 16×. The 64× p95 is over a 30 fps budget; it is
recorded, not claimed away.

## 7. Browser QA (real Dutch GP, headless Chrome at 375/768/1024/1440/1920)

- **Overflow:** none at any width, on the command center or the workbench
  (`scrollWidth = innerWidth`).
- **Command center at LAP 40 with #16:**
  - the panel shows 462 real samples in the 60 s window, latest 165 kph /
    67 % / gear 4 / 10562 rpm, and DRS stated absent;
  - stepping back puts the ghost ring at #16's own location sample,
    labelled with its time.
- **Workbench on the real pair:** R03's two extents are drawn on the real
  circuit, and the NO_DATA tail is listed and not drawn.

Defects found in the browser and fixed:

| finding | fix | test |
|---|---|---|
| telemetry plot 120 px wide in the 303 px column at 1440; values clipped; axis times overlapping | stacked layout under 480 px | `a narrow panel stacks each label and value above a full-width plot` (red first) |
| the lap pickers' `/laps` response aborted the in-flight `/track`, so the length was never prefilled (the unit mock ignored abort signals) | laps and track load independently | `prefills even when the track answers after the laps` (red once the mock honoured aborts) |
| SVG measured with the frame's padding (2 px clip); panel meta run together; picker selects stretched and truncated; A/B monograms overlapping | measure an unpadded element; spacing; picker grid; monogram offsets | verified by screenshot |

## 8. Tests

| suite | new | covers |
|---|---:|---|
| `test_recording_store.py` | 21 | nulls, duplicates, later lap row, corrections, identity, inclusive windows, cache key and corruption rebuilds, catalog shape, spans |
| `test_recording_routes.py` | 8 | evidence bytes = builder; **Singapore rows via a recording = the committed golden**; 422 / 404; RAW keeps every non-null sample; UTC offset; `/laps`; `/sessions` without a DB |
| `test_recording_real.py` | 4 | Dutch GP: evidence builds and validates, `input_digest` recomputed from raw frames; catalog = raw rows; placement = `state_at`; fixture pair follows the rule |
| `test_evidence_spatial.py` | 23 | placement = `driver_state`; NO_DATA / pit / off / stale / coverage reasons; forward across the line; limitations; 9 tamper cases; route 200 / 409 / 404 / 422 |
| `test_evidence_api.py` | +1 assertion | the DB source says `database` |
| `tests/telemetry/telemetry.test.ts` | 21 | fail-closed client (8 tampers); never after the cursor; gaps; DRS; nulls; debounce; driver change; playing prefetch; failure and retry; live |
| `tests/telemetry/panel.test.tsx` | 16 | panel states, hidden table, gap label, keyboard, readout, narrow layout; fail-closed trace; ghost at the own sample, none beyond 2 s |
| `tests/spatial/trackmap.test.tsx` | 2 | ghost at `toPx(x, y)` with its label; none when unvalidated |
| `tests/command/command.test.tsx` | 2 | the panel at LAP 40 on real samples; no request without a driver |
| `tests/evidence/spatial.test.tsx` | 18 | fail-closed placement (9 cases); only PLACED drawn; named segment buttons; unavailable; pickers (lazy, recorded sessions, eligible laps, prefill, race, typed length, no telemetry) |
| `tests/evidence/workbench.test.tsx` | 1 | Singapore: track context unavailable, nothing placed |

**Mutations:** 21 of 21 killed, each applied alone and restored (9 backend,
12 frontend):
- identity guard removed;
- deleted `null` shown as false;
- null read back as 0;
- conflicting duplicate kept;
- recorded lap without a duration given a window;
- NO_DATA or pit lane placed;
- another evidence accepted (backend and frontend);
- extent run backwards;
- sample after the cursor drawn;
- gap bridged;
- non-number accepted;
- another driver's telemetry or trace accepted;
- previous driver's window shown;
- debounce removed;
- ghost from a later sample;
- NOT_PLACED extent drawn;
- pickers offering laps without telemetry;
- prefill over a typed length.

Three first survived; their killing tests were added.

**Final review** (a fresh reviewer, whole branch): "with fixes"; no Critical.
One pass fixed three findings, each with a red-first test:

| finding (re-graded by effect) | fix | test |
|---|---|---|
| Important: after the last sample the panel kept printing that value at the cursor, with no age. The Dutch GP has a real 26 s all-car feed gap (14:29:33–14:29:59). | beyond 2 s the value reads "—"; the stretch to the cursor is drawn and labelled; the header names the last sample's time | `a stale last sample is never shown as the value at the cursor`; `marks the stretch from the last sample to the cursor` |
| Important (was Minor): during a new request the track context paired the new query with the previous evidence, giving a false "could not be loaded" and a failing Retry | placement is requested only for the evidence that answers the current request | `never asks to place a new request with the previous evidence` |
| Important (was Minor): a keyboard-held hovered sample that left the shown minute during playback was read out as "no sample" | a hovered sample counts only inside the shown minute (panel and ghost) | `a hovered sample outside the shown minute is not read as missing` |

The deferred minors are listed in the final report.

## 9. Limitations

- Extents are sample-bounded: consecutive extents leave the stretch between
  two samples uncovered, and a placed end is interpolated between two
  location samples (12A).
- The feed reports one shared line, so A and B extents usually overlap: a
  difference in where they end is a difference in sample times, not in
  racing line.
- Corner-level claims remain unavailable on the Dutch GP (12A corner gate).
- Only the Dutch GP race has a validated track; other sessions show "Track
  context unavailable".
- Live sessions: the telemetry panel and ghost are unavailable (recordings
  and stored sessions only).
- `/sessions` waits for the database connection attempt (~4 s here with
  Postgres down) before answering.
