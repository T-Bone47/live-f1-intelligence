# PHASE 10 — DATA AVAILABILITY

> Tags follow Rule 2's exact vocabulary: OBSERVED (verified directly in
> this repo's code), DOCUMENTED (confirmed via primary-source research,
> whether or not this repo implements it), ASSUMED (this repo's own
> self-flagged uncertainty, in its own words), UNAVAILABLE, UNKNOWN.

## External sources, what was actually checked

**OpenF1** — full API documentation fetched directly from `openf1.org/docs`
and read in full, not sampled. Every endpoint's field list, plus two
limitations OpenF1 documents about *itself*: the `location` endpoint
"lacks details about lateral placement... the origin point (0, 0, 0)
appears to be arbitrary and not tied to any specific location on the
track," and **mini-sectors are "not available during races"**
(qualifying/practice only). Real-time data requires a paid subscription;
historical (2023+) is free. Wind speed unit confirmed m/s directly from
the docs (this repo's own canonical model previously carried an
"upstream unit unconfirmed" comment on that same field — now resolved).

**FastF1** — public docs read for its telemetry model (brake as `bool`,
independently matching this repo's own "binary 0/100" comment on the
same field) and its `circuit_info` API, which is sourced from MultiViewer
and carries FastF1's own explicit caveat: **"manually created and is
not highly accurate but sufficient for visualization."**

**SignalR / F1 live timing** — protocol confirmed from FastF1's own
source and three independent community write-ups: `livetiming.formula1.com/signalr`,
`Streaming` hub, `Subscribe` method, topic list. `CarData.z`/`Position.z`
are raw-DEFLATE compressed on the wire — confirmed against this repo's
own SignalR provider, which already implements the correct decompression
(both `zlib.MAX_WBITS` and negative-window variants), though the row
format inside is self-flagged `ASSUMED` in that same code, pending a
real capture. A real, named reference implementation
(`matteocelani/f1-telemetry`) surfaced hard-won lessons: stuck `InPit`
flags need cross-referencing against stint data, `Retired`/`Stopped`
states need latching, and F1 has been actively IP-blocking third-party
SignalR clients — a live, current access risk, not a historical one.

**F1DB** — unchanged from the Phase 9 finding: deliberately stubbed in
this repo, real upstream project (v2026.12.0 verified active per this
repo's own code comment), building it out is explicitly greenfield.

**ATLAS (Motion Applied)** — confirmed proprietary, no public API or
data schema (`.ssn2` format, SQL Race databases, team-internal). Useful
only conceptually: "parameters" as the base unit, composable "displays,"
and **explicit lap-offset adjustment as a first-class concept** — directly
relevant to this document's synchronization design, sourced from Motion
Applied's own public marketing pages, not inferred.

**Circuit geometry** — two real, non-redundant open sources: MultiViewer/
FastF1's `circuit_info` (local coordinate frame, corner/marshal/rotation
metadata, "not highly accurate but sufficient for visualization" per its
own source) and `bacinger/f1-circuits` (real geographic GeoJSON track
outlines, community-maintained). Different coordinate systems, different
purposes — not competing options.

**Rendering technique research** — multiple independent 2026-dated
sources converge: SVG/Canvas both fine to roughly 3-5k elements; WebGL
pays off past that. `uPlot` (Canvas 2D, ~50KB) specifically benchmarked
for best-in-class cursor/zoom interactivity — a concrete, named
recommendation, not a generic category pick.

## Full matrix

| Field | OpenF1 | SignalR | FastF1 | Historical | Current canonical model | Replay viable? |
|---|---|---|---|---|---|---|
| x/y/z | OBSERVED — real endpoint, real mapping in this repo (`to_location_sample`) | ASSUMED — decompression real, row format unverified | DOCUMENTED upstream, **not implemented** here | = OpenF1 (free, 2023+) | `TelemetryLocationSample(x,y,z)` | **Yes, via OpenF1** — the only working path |
| distance along lap | UNAVAILABLE as a raw field | UNKNOWN | DOCUMENTED (FastF1 computes via speed integration), not implemented here | derivable, not stored | absent entirely | Only via derivation (see synchronization doc) |
| timestamp | OBSERVED | DOCUMENTED (`utc` field, per this repo's own protocol comment) | DOCUMENTED | = OpenF1 | present on every sample | Yes |
| speed | OBSERVED | ASSUMED | DOCUMENTED, not implemented | = OpenF1 | `speed_kph` | Yes, via OpenF1 |
| throttle | OBSERVED | ASSUMED | DOCUMENTED, not implemented | = OpenF1 | `throttle_pct` | Yes, via OpenF1 |
| brake | OBSERVED — **binary 0/100, not continuous** (this repo's own comment; independently matches FastF1's own `bool` typing) | ASSUMED | DOCUMENTED, not implemented | = OpenF1 | `brake_pct` | Yes, with the binary caveat carried through |
| gear | OBSERVED | ASSUMED | DOCUMENTED, not implemented | = OpenF1 | `gear` (int) | Yes |
| RPM | OBSERVED | ASSUMED | DOCUMENTED, not implemented | = OpenF1 | `rpm` | Yes |
| DRS | OBSERVED — raw code, not decoded; real code table found (0/1 off, 8 eligible, 10/12/14 on; 2/3/9 undocumented even upstream) | ASSUMED | DOCUMENTED (int + interpretation table), not implemented | = OpenF1 | `drs` (raw code) | Yes, needs a decode step this repo doesn't have |
| lap number | OBSERVED | OBSERVED | OBSERVED | OBSERVED | solid | Yes |
| sectors (S1/S2/S3) | OBSERVED | OBSERVED | OBSERVED | OBSERVED | `Lap.sector1_s/2_s/3_s` — already in schema | Yes |
| mini-sectors | DOCUMENTED — **"not available during races"** per OpenF1's own docs | DOCUMENTED via a real reference implementation | UNAVAILABLE — this repo's adapter explicitly declares `mini_segments=False` | qualifying/practice only | `SectorTime.segment_codes` exists | Qualifying/practice only, never race replay |
| tyre | OBSERVED | OBSERVED | OBSERVED | OBSERVED | `TyreStint`, wired | Yes |
| position (ranking) | OBSERVED | OBSERVED | OBSERVED | OBSERVED | `LeaderboardRow.position` | Yes |
| gaps/intervals | OBSERVED | OBSERVED | OBSERVED | OBSERVED | `gap_to_leader_s`/`interval_s` | Yes |
| race-control | OBSERVED, plus a `qualifying_phase` field this repo doesn't use yet | DOCUMENTED (`RaceControlMessages` topic) | OBSERVED | OBSERVED | wired | Yes |
| circuit geometry | UNAVAILABLE in this repo (F1DB stub) | N/A | N/A | PROPOSED: two real sources found (above) | absent | Not yet — real, buildable, not invented |

## Sufficiency by use case
1. **Race replay** — timing/position/gaps/tyres/race-control solid.
   Telemetry works via OpenF1 (live needs its paid tier; historical is
   free). **Mini-sectors don't exist for races at all**, by OpenF1's own
   design — not a gap in this repo to fix.
2. **Qualifying lap comparison (flagship)** — the best-supported case:
   full telemetry, sectors, *and* mini-sectors all available via the one
   already-working OpenF1 path. Missing: distance-along-lap (derive it),
   circuit geometry (build it, calibration-gated), DRS decode (small gap).
3. **Track animation** — has raw x/y/z now; needs circuit geometry for
   spatial meaning. Dots-on-blank-background works today; positioned on
   a real track needs the calibration step in the synchronization doc.
4. **Delta calculation** — the single missing piece is distance-along-lap
   normalization. Everything else needed already exists.
5. **Corner analysis** — needs circuit geometry *with* corner metadata,
   which is exactly what MultiViewer/FastF1's `circuit_info` provides —
   with its own "not highly accurate" caveat carried forward.
