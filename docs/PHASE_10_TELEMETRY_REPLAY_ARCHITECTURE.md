# PHASE 10 — TELEMETRY REPLAY & VISUALIZATION ARCHITECTURE

> Research + architecture only. No code changed in this phase. Every claim
> below is tagged OBSERVED (verified directly in this repo's code this
> phase), DOCUMENTED (confirmed via primary-source research), ASSUMED
> (this repo's own self-flagged uncertainty, in its own words), or
> PROPOSED (new design, not yet built). Companion documents:
> `PHASE_10_DATA_AVAILABILITY.md`, `PHASE_10_LAP_SYNCHRONIZATION.md`,
> `PHASE_10_RENDERING_ARCHITECTURE.md`, `PHASE_10_API_CONTRACT.md`.

## 1. Existing reusable infrastructure (Rule 1)

**Canonical telemetry model** (`core/models.py`) — OBSERVED, real, already
correct: `TelemetryCarSample` (rpm, speed_kph, gear, throttle_pct,
brake_pct, drs) and `TelemetryLocationSample` (x, y, z) are separate
models. `brake_pct` is binary 0/100 in practice despite its float type
(the model's own comment says so — independently matches FastF1's own
model, which types brake as `bool`). `Lap` already carries
`sector1_s`/`sector2_s`/`sector3_s`, `is_pit_out_lap` (genuinely wired),
and `deleted` (real field, **never set anywhere in the codebase** — its
own comment says "future phase").

**Recording is already full-fidelity.** `Recorder.write(envelope)`
persists canonical `Envelope`s — the same post-normalization objects
`AnalysisEngine.process_envelope()` consumes — one per JSONL line,
zstd-compressed. No sampling, no coalescing, at the recording layer.
`ReplayProvider.run()` reads every line back via `Envelope.model_validate`
and re-wraps each as a `RawItem` with a `{"__envelope": ...}` marker that
the ingest pipeline recognizes to skip re-normalization entirely — proven
by its own docstring's claim, "live/replay share one interface." Pacing
(`_paced`) computes each inter-frame delay from the *original* timestamp
gap between consecutive envelopes, not from an accumulated running clock
— self-correcting against drift by construction (§9 detail).

**Live telemetry is deliberately lossy — the coalescer is downstream of
recording, not upstream.** `TelemetryCoalescer` does 5Hz latest-wins
coalescing (~3.5Hz native rate per car, documented in its own code
comment) specifically for the live WS broadcast path. It never touches
what gets recorded. This resolved Rule 4's central question: full-fidelity
replay data already exists in every recording; it was never a recording
problem.

**Persistence is fully built and completely unwired.** `telemetry_car`/
`telemetry_location` tables exist in `001_init.sql` with correct composite
indexes; `005_telemetry_history.sql` adds TimescaleDB compression and a
documented downsampling-tier strategy (RAW/HIGH/MEDIUM/LOW). Real,
batched insert functions (`insert_car_samples_bulk`,
`insert_location_samples_bulk`, `insert_events_bulk`) have real callers —
in `PersistenceSubscriber` (`ingest/persistence.py`), a complete,
well-designed subscriber class whose own comment says the event log
exists partly for **"replay parity evidence."** But `PersistenceSubscriber`
is never instantiated or attached to the envelope stream anywhere.
**No telemetry sample has ever been written to Postgres in this
codebase's current state.** The already-correct `/telemetry/{driver}`
endpoint (LTTB downsampling, confirmed correct) has therefore always
returned empty results, for every session, live or replayed — a fact
that was invisible from the read side alone.

**WS contract** (`realtime/hub.py`, `realtime/differ.py`) — 6 real frame
kinds (`SNAPSHOT`, `DELTA`, `EVENTS`, `TELEMETRY`, `CONTROL`, `PONG`),
sequenced, per-client opt-in telemetry subscriptions by driver.

**No track-geometry code exists anywhere** (confirmed by direct search,
not assumed absent) — genuinely greenfield, not a case of "reuse existing
infrastructure" applying.

## 2-3. External research & data matrix
See `PHASE_10_DATA_AVAILABILITY.md` for the full matrix and every source.
Headline finding: **OpenF1 is currently the only working, implemented
telemetry path** in this codebase. FastF1's adapter declares
`telemetry_car=True, telemetry_location=True` but has zero code that
processes car/location DataFrames — declared, not implemented. SignalR's
`.z` channel decompression is real and correct, but its row format is
self-flagged `ASSUMED` pending a real capture.

## 4. Recommended replay architecture (Rule 4)
Not a redesign — one wiring connection. Attach `PersistenceSubscriber` to
the envelope stream in `build_runtime()` for both live and replay
sessions. That single connection makes the already-correct
`/telemetry/{driver}` endpoint start returning real data and makes a new
bulk per-lap comparison endpoint (§ API contract doc) a straightforward
addition on already-indexed tables, not a new subsystem.

## 5. Recommended synchronization algorithm
See `PHASE_10_LAP_SYNCHRONIZATION.md`. Summary: distance-along-lap derived
primarily by trapezoidal integration of `speed_kph` (matches FastF1's own
documented approach, buildable today, no geometry dependency), normalized
to percent-of-lap-distance (not raw meters) so racing-line differences
between drivers don't misalign corners, with both drivers resampled onto
a shared distance grid for delta calculation.

## 6. Track-coordinate architecture
See `PHASE_10_LAP_SYNCHRONIZATION.md`. Summary: primary centerline is
self-referential — built from a session's own clean reference lap, zero
cross-source alignment risk. External geometry (two real sources found:
MultiViewer/FastF1 `circuit_info`, `bacinger/f1-circuits` GeoJSON) is a
calibration-gated enhancement layer for labels and pre-session display,
not a hard dependency for car-position math, because neither source's
alignment with OpenF1's telemetry frame has been verified.

## 7. Rendering architecture
See `PHASE_10_RENDERING_ARCHITECTURE.md`. Summary: SVG for the track map
and event timeline (native hit-testing, small element counts); Canvas via
`uPlot` for the synchronized telemetry/delta chart stack (built for
exactly this cursor-sync case). WebGL not recommended at the flagship
2-driver scope — a real threshold to revisit if scope grows to full-field
replay, not a permanent no.

## 8. API changes required
See `PHASE_10_API_CONTRACT.md`.

## 9. Performance model & 10. Risks
See §9 risk list, folded into this document below rather than a sixth
file — it's a list, not a standalone design.

### Risks (Rule 9), in the requested order
1. **Replay clock drift** — inter-stream drift is architecturally low
   (one ordered, timestamp-anchored sequence for everything); the real,
   bounded risk is aggregate wall-clock pacing accuracy under
   `asyncio.sleep` scheduling load, not divergence between subsystems.
2. **Telemetry sampling mismatch** — ~3.5Hz irregular native rate; solved
   by resampling onto a common distance grid, not by comparing raw
   samples directly.
3. **x/y/z coordinate assumptions** — "arbitrary origin" (OpenF1's own
   words) doesn't imply cross-source compatibility. Solved by the
   self-referential centerline plus mandatory calibration for external
   geometry.
4. **Live-vs-replay data differences** — recordings are frozen at capture
   time; a post-session lap deletion or penalty won't appear in a replay
   of the original recording unless a separate patch mechanism exists.
   Not currently addressed anywhere; a real product decision, not an
   oversight to silently inherit.
5. **Full-fidelity recording size** — PROPOSED estimate (not measured):
   roughly 250-350MB raw for a full 2-hour race's car+location telemetry
   across ~20 cars, likely 30-60MB zstd-compressed. The flagship feature's
   actual need (2 drivers, 1 lap) is kilobytes.
6. **Browser memory** — only a real risk if naively extended to
   "load a full race." The already-designed (not yet wired) LTTB
   downsampling tiers exist specifically to prevent this for full-race
   views; the flagship comparison doesn't need them at all.
7. **Interpolation errors** — naive interpolation across a real gap would
   smooth away exactly the transient (lockup, spin) someone wants to see.
   Addressed by an explicit gap threshold with honest degradation.
8. **Lap alignment errors** — boundary continuity around restarts;
   sourcing both compared drivers from the same provider avoids a
   cross-provider boundary-definition bias.
9. **Qualifying invalid laps** — `is_pit_out_lap` real and usable now;
   `deleted` real but never wired. `race_control.qualifying_phase`
   (DOCUMENTED upstream, not in this codebase) could help exclude
   wrong-segment laps once built.
10. **Pit-lane geometry** — naive centerline projection would show a
    pitting car "stuck" on the main straight. `LeaderboardRow.in_pit` is
    real and already used elsewhere; suppress projection while true.
11. **Track geometry availability** — two real sources, calibration-gated;
    F1DB remains a stubbed third option (Phase 9 finding), not available.
12. **22-driver replay** — out of the flagship's scope; would need Rule
    4's persistence wiring plus the downsampling tiers, and would push
    toward Canvas/WebGL (§ rendering doc's stated threshold).
13. **60 FPS rendering** — a render-loop concern, not a data claim: real
    telemetry tops out near 3.5Hz; 60fps means smooth interpolation
    between real points, never implies 60Hz of measured data.

## 11. Exact implementation order
Not yet authorized — Phase 10.1 is explicitly not started per this
phase's STOP condition. If and when it is:
1. Wire `PersistenceSubscriber` into `build_runtime()` (live + replay).
   Unblocks the already-correct `/telemetry/{driver}` endpoint and every
   downstream item.
2. Build the distance-along-lap derivation (speed integration) as a
   backend analysis module, following this codebase's existing
   `analysis/` module pattern.
3. Build the bulk per-lap comparison endpoint (§ API contract doc).
4. Build the self-referential centerline + projection module.
5. Frontend: telemetry trace stack (`uPlot`) + track map (SVG) against
   real data from steps 1-3, before attempting external-geometry
   calibration.
6. External geometry calibration (MultiViewer/FastF1 `circuit_info` or
   `bacinger/f1-circuits`) as a separate, later addition — genuinely
   optional for the flagship feature to function correctly.

---
**STOP. Not proceeding into Phase 10.1 implementation.**
