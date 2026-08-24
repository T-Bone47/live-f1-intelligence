# DATA_SOURCES.md

| | |
|---|---|
| Status | Phase 0 research + **Phase 1 empirical findings (§11)** |
| Confidence | High for OpenF1 / Jolpica / FastF1 / livetiming feed; Medium for F1DB (not deeply audited) |

---

## 1. Executive answer to "what live data can actually be obtained?"

**Yes, real live F1 timing + telemetry is obtainable through two legitimate
routes**, both unofficial/community:

1. **The F1 official live-timing stream directly**
   (`livetiming.formula1.com`, SignalR Core WebSocket). This is the same feed
   that powers the official F1 live-timing web app. Latency ≈ real time.
   Mid-2026 it migrated from legacy `/signalr` to `/signalrcore` with a new
   text protocol. Authentication state is **ambiguous**: multiple independent
   projects (f1-dash production as of June 2026) connect without any token and
   receive full snapshots + feeds; FastF1's client officially requires an F1
   account login. Treat "no-auth works" as an unguaranteed privilege that may
   be revoked → pluggable auth required.

2. **OpenF1** (`api.openf1.org`) — a community service that ingests the same
   upstream stream and re-serves it. Historical access free; **live access
   during sessions requires their €9.90/month sponsor tier**, delivered via
   REST, MQTT or WebSocket. Stated latency ~3 s behind live events.

Everything else (Jolpica, FastF1-as-library, F1DB) is historical/reference,
not live.

There is **no official public commercial API** for F1 live timing open to the
general public.

## 2. Source-by-source assessment

### 2.1 F1 official livetiming stream (direct)

| Attribute | Finding |
|---|---|
| Endpoint | `https://livetiming.formula1.com/signalrcore` (HTTP negotiate + WSS) |
| Protocol | SignalR Core, JSON protocol, messages delimited by `\x1e`; handshake `{"protocol":"json","version":1}`; initial state arrives as completion (type 3); incremental frames as invocations targeting `"feed"` with args `[topic, data, timestamp]`; type-6 keep-alive pings must be skipped |
| Auth | Ambiguous: reports of token-less connects working (residential IP, byte-identical snapshot vs. tokened run); FastF1 documents F1TV login requirement; bearer token TTL ~4 days when used. **Design for both modes.** |
| Topics | `Heartbeat`, `CarData.z`, `Position.z`, `ExtrapolatedClock`, `TopThree`, `RcmSeries`/`RaceControlMessages`, `TimingStats`, `TimingAppData`, `WeatherData`, `TrackStatus`, `DriverList`, `SessionInfo`, `SessionStatus`, `SessionData`, `LapCount`, `TimingData`, `TeamRadio`, `AudioStreams`, `ContentStreams` |
| CarData.z | Deflate-compressed CSV rows per car: UTC, RPM, speed, nGear, throttle, brake, DRS — ~3.5 Hz per car (~200 ms batches covering all cars) |
| Position.z | Deflate-compressed x,y,z per car, ~3.7 Hz, coarse (no meaningful lateral resolution), arbitrary origin |
| TimingData | Gaps/intervals/position, sector times + segment (mini-sector) states, speeds at traps, best/last lap, pit flags, retired status |
| TimingAppData | Stints (compound, new/used, laps on tyre), per-lap times, pit stop durations |
| RaceControlMessages | Flags (yellow/double yellow/chequered), SC/VSC deploy & in-this-lap, red flag, penalties + reasons, investigations, track-limit deletions, blue flags |
| WeatherData | air_temp, track_temp, humidity, pressure, wind_direction, wind_speed, rainfall — roughly every 30–60 s |
| Update frequency | Continuous push; CarData/Position batch every ~200 ms; timing bursts several msgs/s |
| Latency | Effectively source-of-truth (~0–2 s behind reality; same feed as the official app). We will measure our own p50/p95 in Phase 2 rather than trust folklore. |
| Reliability | Server force-disconnects long-lived connections (~2 h observed by recorders) → supervisor with reconnect + snapshot resync mandatory |
| Rate limits | Unknown/unpublished; single connection per consumer is normal usage |
| Restrictions | Unofficial use; ToS risk; see §9 |
| Cost | Free today (no-auth mode) / F1TV account path |

### 2.2 OpenF1

| Attribute | Finding |
|---|---|
| Endpoint | `https://api.openf1.org/v1/<resource>` (+ MQTT/WebSocket for sponsors) |
| Model | Community project that ingests the same upstream feed; open source (can self-host the whole ingest stack ourselves later) |
| Endpoints (18) | `car_data`, `location`, `sessions`, `meetings`, `drivers`, `laps`, `intervals`, `position`, `pit`, `stints`, `race_control`, `weather`, `team_radio`, `overtakes`, `session_result`, `starting_grid`, `championship_drivers`, `championship_teams` |
| Live availability | **Paid tier only during sessions** (window = session start −30 min … end +30 min). Sponsor tier €9.90/mo: REST + MQTT + WS, 6 req/s, 60 req/min, ≤10 concurrent MQTT/WS connections |
| Historical | Free, no auth: 2023 season → now, JSON/CSV |
| Telemetry fidelity | car_data & location ~3.7 Hz; intervals/positions ~4 s cadence; weather ~60 s |
| Latency | ~3 s stated for live data |
| Rate limits (free) | 3 req/s, 30 req/min |
| Auth | None for historical; account/token for sponsor tier |
| Reliability | Good but has had live-session instability historically (motivated their paid infra upgrade) |
| Licensing | Project under CC BY-NC-SA 4.0; explicitly non-commercial intent; disclaims ownership of F1 data; not affiliated with FOM/FIA |
| Self-host | Possible (open source): we could run OpenF1's own scraper+API internally if upstream direct feed breaks |

### 2.3 Jolpica-F1 (Ergast successor)

| Attribute | Finding |
|---|---|
| Endpoint | `https://api.jolpi.ca/ergast/f1/...` (Ergast-compatible JSON; no XML) |
| Role | Schedule/meetings, results, qualifying results, sprint results, lap summaries, pit stops, standings, circuits/drivers/teams reference data |
| Live | **No.** Post-season-session updates, committed ≥ weekly (Monday), aiming for hours-after eventually |
| Rate limits | Unauthenticated: 4 req/s burst, 500 req/h sustained; API tokens planned; limits expected to tighten |
| Use for us | Session calendar, driver/team metadata cross-check, historical standings/results backfill, championship context for AI |
| Risk | Low technical risk; do not poll near limits; cache aggressively |

### 2.4 FastF1 (library)

| Attribute | Finding |
|---|---|
| What it is | Python library: post-session parser of the livetiming API into Laps / Telemetry / Weather DataFrames; includes a raw SignalR recorder client (now SignalR Core; officially needs F1TV auth) and a `LiveTimingData` loader for recorded files |
| Live | Explicitly **not** real-time processing capable ("data can [only] be processed after the session") |
| Use for us | (a) Cross-validation oracle for our own parser on historical sessions; (b) prototyping analytics; (c) emergency recorder fallback. Not a runtime dependency of the live pipeline. |
| Caveats | Requires local cache; mixing API-loaded and recorded data for one session is discouraged; connection drop ~2 h |

### 2.5 F1DB

| Attribute | Finding |
|---|---|
| What it is | Community-maintained complete-history database (CSV/Parquet releases) of seasons, races, drivers, teams, results, qualifying, laps |
| Live | No. Static periodic dataset dumps |
| Use for us | Optional bulk reference/history import (e.g., career stats for AI context). Medium confidence until audited; verify schema + update cadence before Phase 4 |

### 2.6 Rejected / not pursued

| Source | Reason |
|---|---|
| Ergast | Shut down early 2025 (Jolpica is the successor) |
| Official F1 partner feeds (AWS/Stats Perform class) | Commercial licensing, not publicly accessible |
| Scraping third-party dashboards (f1-dash etc.) | Adds dependency on another fan project; f1-dash is AGPL-3.0 (code reuse would force AGPL on us) — architecture study only, zero code reuse |
| Gaming APIs (F1 23/24 UDP) | Wrong domain (sim game telemetry ≠ real sessions) |

## 3. Verified capability matrix

Legend: ✔ available · ✖ unavailable · ◑ partial/conditional

| Capability | Direct livetiming feed | OpenF1 live (paid) | OpenF1 historical (free) | Jolpica | FastF1 |
|---|---|---|---|---|---|
| Live timing/gaps | ✔ | ✔ (~3 s) | ✖ | ✖ | ✖ |
| Sector times | ✔ (TimingData) | ✔ via laps | ✔ post-session | ◑ quali only | ✔ |
| Mini-sectors | ◑ segment states in feed | ✖ | ✖ | ✖ | ✖ |
| Car telemetry 6-ch @~3.5 Hz | ✔ CarData.z | ✔ car_data | ✔ | ✖ | ✔ |
| GPS position | ✔ Position.z | ✔ location | ✔ | ✖ | ✔ |
| Speed trap / ST traps | ✔ | ◑ laps.speed_st_* | ✔ | ✖ | ✔ |
| Tyre stints/compounds | ✔ TimingAppData | ✔ stints | ✔ | ✖ | ✔ |
| Pit stops w/ duration | ✔ | ✔ pit | ✔ | ✔ race pits | ✔ |
| Weather | ✔ ~30–60 s | ✔ ~60 s | ✔ | ✖ | ✔ |
| Race control messages | ✔ | ✔ | ✔ | ✖ | ✔ |
| Team radio (audio URLs) | ✔ | ✔ | ✔ | ✖ | ✔ |
| Overtake events | ◑ derivable from position/timing | ✔ overtakes endpoint | ✔ | ✖ | ◑ |
| Results/grid/standings | ◑ SessionData | ✔ endpoints | ✔ | ✔ | ✔ |
| Session schedule | ◑ SessionInfo | ✔ sessions/meetings | ✔ | ✔ | ✔ |
| Championship points live | ✖ (derive) | ✔ championship_* | ✔ final | ✔ final | ✖ |
| Driver biometrics / tyre temps / fuel / ERS | ✖ | ✖ | ✖ | ✖ | ✖ |

## 4. Provenance classification applied to our features

| Class | Sources feeding it |
|---|---|
| A Direct live | signalrcore topics; OpenF1 live (fallback) |
| B Historical | OpenF1 historical, Jolpica, FastF1-parsed archives, our own recordings |
| C Derived | everything in analysis engine (pace, sectors aggregates, battles, windows…) |
| D Predictions | degradation model, race projection, elimination projection |
| E LLM interpretation | AI engineer outputs |
| F Unavailable | tyre temps, fuel, ERS, battery, high-rate ECU, precise lateral GPS, team encrypted strategy comms |

## 5. Frequency & latency summary (verified numbers)

| Stream | Native cadence | Realistic end-to-end latency (our budget ≤ +1 s processing) |
|---|---|---|
| CarData.z / Position.z | ~3.5–3.7 Hz/car, ~200 ms batches | ~0.5–2.5 s (direct) |
| TimingData updates | bursty, several/sec | ~0.5–2 s (direct); ~3–5 s via OpenF1 |
| Intervals/position table | ~4 s | same |
| Weather | ~30–60 s | negligible impact |
| RCM | event-driven, instant | < 1 s (direct) |
| OpenF1 REST polling floor | request-driven | bounded by rate limit + 3 s service lag |

## 6. Provider abstraction requirements (drives ARCHITECTURE.md)

Any provider must expose, after normalization:
session lifecycle events, timing deltas, lap completions with sector splits,
telemetry samples (canonical units, UTC timestamps), stint changes, pit events,
weather samples, RCM messages, driver/team registry, and a `capabilities()` 
descriptor declaring exactly which streams it supports so analyzers/UI degrade 
honestly instead of guessing.

Two concrete providers for MVP: `LiveTimingProvider` (primary, direct),
`OpenF1Provider` (secondary: live-paid mode and historical mode share code).
`ReplayProvider` emits stored canonical frames through the same interface.

## 7. Update-strategy notes

- Direct feed = subscribe once, push forever; reconnect supervisor mandatory.
- OpenF1 live = MQTT/WS subscription preferred over REST polling (rate limits).
- Historical backfill = REST with pagination + local cache keyed by session_key;
  respect 3 req/s.
- Jolpica = nightly sync job only; never on the hot path.

## 8. Data-quality observations to design for

- Upstream timing gaps/intervals occasionally disagree between TimingData and
  recomputation from lap times → store both, prefer feed values, flag conflicts.
- Lap-time deletions (track limits) arrive as RCM after the fact → laps must be
  mutable records with deletion tombstones.
- Feed outages mid-session happen → recorder gap markers, replay stitching,
  and "data gap" UI states are first-class concepts.
- Session clock vs wall clock drift → ExtrapolatedClock + Heartbeat used to
  maintain a monotonic session timeline.

## 9. Legal & licensing posture

1. No official license exists for hobby-scale consumption of this feed; all
   viable sources are unofficial. Projects operate under long-standing
   fan-project tolerance.
2. Our posture: **non-commercial, attributed, low-volume, takedown-ready**;
   no resale of raw data; no public redistribution of raw recordings; derived
   insights only leave the system as analyses.
3. Trademark care: avoid implying officialness; follow F1 brand-use norms in
   product naming/assets.
4. OpenF1 data/code is CC BY-NC-SA 4.0 → non-commercial compatible; attribution
   required; share-alike applies to their code/data we redistribute.
5. f1-dash is AGPL-3.0 → **zero code reuse**; protocol knowledge only.
6. If commercialization ever happens, pursue licensed data (e.g., official
   partners) — out of scope for MVP.

## 10. Answers to Phase-0 questions (condensed)

1. **What live data?** Full timing + 6-channel telemetry + coarse GPS + tyres +
   weather + RCM (see §1).
2. **From where?** signalrcore direct (primary), OpenF1 paid live (fallback).
3. **Frequency?** §5 table.
4. **Latency?** sub-2 s direct / ~3 s OpenF1, measured not assumed.
5. **Genuine telemetry?** speed/throttle/brake/gear/RPM/DRS @3.5 Hz + xyz GPS.
   Nothing more exists publicly (class F list).
6. **Calculate ourselves?** All pace/degradation/battle/strategy/theoretical
   metrics; canonical laps from raw splits; distance-around-lap; mini-sector
   timings (phase 6).
7. **Statistical/ML?** Degradation curves, remaining-life estimates, race
   projection Monte Carlo, traffic inference refinements.
8. **LLM?** Explanations, Q&A, narratives over deterministic context packs only.
9. **Cannot reliably implement?** Anything requiring class-F channels; instant
   (<300 ms) guarantees; guaranteed uptime of sources; mini-sectors beyond
   feed-provided segments without own track maps.
10. **Source risks?** §TECHNICAL_RISKS.md R1–R6 (auth change, shutdown,
    rate limits, format drift, legal posture, outage handling).

---

## 11. PHASE 1 EMPIRICAL FINDINGS (implemented + measured 2026-08-23)

Findings below come from building and running the actual ingestion pipeline
against the real **2026 Dutch GP Race (session_key 11353)** — not from docs.

### What we expected vs what the source provided

| Expectation | Reality | Action |
|---|---|---|
| `year=` filter lists seasons | Returns "No results found" even for existing seasons | discovery scans meeting keys instead |
| Empty results = HTTP 200 `{"detail":"No results found."}` | TRUE but also arrives as **HTTP 404** with same body | client treats both as [] |
| laps filterable by `date>` | silently returns [] — laps filters on **`date_start>`** | fixed client |
| intervals gap fields numeric | MIXED: floats AND strings (`"+1 LAP"` for lapped cars) | numeric column NULL + verbatim `gap_raw` |
| car_data.drs always 0–15 code | nullable in real data | preserved as NULL |
| rcm.sector = timing sector 1–3 | marshal-post numbers (7, 14, 18 observed) | stored as `marshal_sector` |
| stints have timestamps | none → cannot cursor | full refresh + dedupe |
| pit.stop_duration present | nullable; lane_duration present | kept nullable |
| rate limit 3 rps / 30 rpm | HTTP 429s occur well before documented limits, escalating Retry-After penalties | client defaults 1.8 rps / 20 rpm |

### What was missing / unavailable

- No live-window access without sponsor token (acceptance session was
  post-session → historical backfill path exercised end-to-end instead).
- No lap deletion tombstones in laps endpoint (RCM-based derivation deferred).
- Team radio endpoint exists but is out of Phase-1 scope.

### What was derived

Nothing yet beyond normalization itself (Phase-1 scope): canonical models,
sector rows split from lap payloads, RCM content-hash dedupe keys.

### What proved unreliable

- Sustained-rate behavior near documented limits (see table).
- Nothing else: after fixes, a full-race backfill completed with
  **0 malformed records** across 1.07M events.

### Verified volumes & counts (single race session)

laps 1,373 · sectors 4,119 · car telemetry 530,166 · location 499,290 ·
stints 87 · pits 65 · weather 183 · rcm 329 · positions 586 ·
intervals 30,613 (incl. 8,629 lapped-car rows).

### Live latency

Not measurable this phase (no live window available during testing).
Measurement machinery implemented + unit-tested; first live run must publish
class-A p50/p95 before any "real-time" claim is made.

---

## 12. PHASE 1.5 ADDITIONS (2026-08-24)

- **SignalR Core feed VERIFIED token-less**: negotiate HTTP 200 +
  connectionToken; WSS handshake ACK; subscribe returned a type-3 snapshot
  containing Heartbeat, DriverList, SessionInfo, TimingData, WeatherData,
  RaceControlMessages (probe: `scripts/probe_signalr.py`). Incremental frame
  formats remain ASSUMED until a live capture. Legacy `/signalr` returns 401
  (dead).
- **Jolpica VERIFIED**: 2026 schedule = 23 races; current driver standings
  served. Weekly update cadence confirmed by project docs.
- **FastF1 3.8.3** installs and loads the Jolpica-backed 2026 schedule;
  adapter (`providers/fastf1/`) maps laps/weather into canonical models,
  always class B.
- **F1DB**: active release v2026.12.0 (published 2026-08-23); strategy =
  offline reference import only.
- Full comparison: `docs/PROVIDER_COMPARISON.md`; priorities/reconciliation/
  failover/runbook: `docs/LIVE_DATA_STRATEGY.md`.
