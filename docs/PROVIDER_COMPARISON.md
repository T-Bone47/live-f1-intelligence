# PROVIDER_COMPARISON.md

| | |
|---|---|
| Status | Phase 1.5 — claims graded VERIFIED / PARTIAL / UNKNOWN per row |
| Rule | No unsupported claims. UNKNOWN means we have not proven it. |

Legend: **YES** verified available · **PARTIAL** available with caveats ·
**NO** not available · **UNKNOWN** unverified · **N/A** outside source's purpose.

---

## 1. Summary matrix

| Dimension | OpenF1 | F1 SignalR (direct) | FastF1 | Jolpica | F1DB |
|---|---|---|---|---|---|
| Purpose | Community REST API over official feed | Official live-timing feed itself | Python post-session analysis library | Ergast-successor results API | Bulk historical reference DB |
| Live capability | **PARTIAL** (paid tier only, in-window; free = historical REST polling) | **YES** (negotiate/handshake/snapshot verified token-less 2026-08-24; live frames UNVERIFIED until a session is captured) | NO | NO | NO |
| Historical capability | YES (2023+, free) | NO (no archive surface via this endpoint family) | YES (full sessions incl. telemetry) | YES (results/standings/schedule; laps summary) | YES (1950+ reference/results, no telemetry) |
| Car telemetry (6-ch ~3.5 Hz) | YES | ASSUMED (CarData.z topic documented; capture pending) | YES (post-session) | NO | NO |
| GPS position | YES (~3.7 Hz coarse) | ASSUMED (Position.z) | PARTIAL (pos data post-session) | NO | NO |
| Timing gaps/intervals | YES (~4 s cadence) | ASSUMED (TimingData) | PARTIAL (recomputed from laps) | PARTIAL (lap-position summaries only) | NO |
| Laps + sectors | YES (verified shapes) | ASSUMED (TimingData/TimingStats) | YES | PARTIAL (lap summaries, no sector detail) | PARTIAL (race lap lists) |
| Mini-segments | YES (verified arrays in laps rows) | UNKNOWN | NO | NO | NO |
| Tyres/stints | YES | ASSUMED (TimingAppData) | YES | NO | NO |
| Pit stops | YES (stop_duration nullable) | ASSUMED | YES | YES (race pits only) | YES (historical pits) |
| Weather | YES (~60 s) | ASSUMED (WeatherData) | YES | NO | NO |
| Race control | YES (marshal-sector quirk documented) | ASSUMED (RaceControlMessages topic presence VERIFIED in snapshot) | PARTIAL (track status + RCM where parsed) | NO | NO |
| Positions | YES (change events) | ASSUMED | PARTIAL (finishing positions) | YES (results order) | YES (historical results) |
| Results / standings | PARTIAL (session_result endpoints) | NO | PARTIAL (session results) | YES (verified: 2026 schedule=23 races, standings served) | YES |
| Schedule/discovery | PARTIAL (`year=` broken; meeting-key scan works) | NO (no registry) | YES (Jolpica-backed; verified load) | YES (verified) | YES (seasons/races) |
| Update frequency | Poll-bound (our client ≤ ~2 rps); upstream lag ~3 s claimed | Push, near-real-time (same feed as official app — latency MEASUREMENT PENDING) | Static post-session | Weekly-ish post-session commit | Periodic dataset releases (v2026.12.0 on 2026-08-23) |
| Latency (live) | UNKNOWN until measured (claimed ~3 s) | MEASUREMENT PENDING (architecture implies sub-second–few s) | N/A | N/A | N/A |
| Reliability (observed) | GOOD w/ strict rate limits (429s below documented caps) | UNKNOWN long-term (auth posture historically unstable; ~2 h server disconnects reported by community) | GOOD (mature lib) | GOOD | GOOD |
| Authentication | None historical / token for live window | NONE required today (VERIFIED); may change any time → pluggable bearer | None (Jolpica-backed schedule) | None (rate-limited) | None (download releases) |
| Rate limits | Documented 3 rps/30 rpm; EMPIRICALLY stricter (429s) — client runs 1.8 rps/20 rpm | Unknown/unpublished; single connection normal usage | N/A (their cache+limits apply to Jolpica calls) | 4 rps / 500 rpm documented | N/A |
| Deployment compatibility | YES (plain HTTPS; works from servers) | LIKELY YES (WSS; verified from Windows workstation; cloud egress to F1 CDN typically fine) | YES (local compute; heavy downloads) | YES (HTTPS) | YES (file download/import) |
| Licensing / usage | CC BY-NC-SA project; non-commercial fan posture; disclaims F1 ownership | Unofficial use of publicly exposed feed; ToS risk; takedown-ready posture required | MIT library over same unofficial sources | Open-source project; fair-use rate limits | Open data releases |
| Strengths | Zero-auth historical; rich normalized endpoints; self-hostable upstream exists | Lowest possible latency + richest topics (mini-segments, traps, app-level stats) | Gold-standard parsed telemetry/laps for backtesting & validation | Clean results/standings/schedule; Ergast compatibility | Complete career/reference metadata, actively maintained |
| Weaknesses | Not push; quota-tight; live behind paywall | Auth instability risk; format drift risk; no archive | Never live; heavy loads; pandas dependency | No telemetry/weather; weekly updates | No session/live data; import-only |

## 2. Verification ledger (what WE personally proved)

| Claim | Proof date | Method |
|---|---|---|
| OpenF1 full-race ingest 1,067,193 events, 0 malformed | 2026-08-23 | Phase-1 acceptance run |
| OpenF1 `year=` broken; `date_start>` on laps; `+1 LAP` gaps; nullable drs; 404-empty quirk; marshal-sector values >3 | 2026-08-23 | Phase-1 pipeline + probes |
| SignalR negotiate HTTP 200 token-less; WSS handshake ACK; subscribe snapshot with Heartbeat/DriverList/SessionInfo/TimingData/WeatherData/RaceControlMessages | 2026-08-24 | `scripts/probe_signalr.py` |
| Jolpica 2026 schedule (23 races) + current driver standings served | 2026-08-24 | Direct REST probe |
| FastF1 3.8.3 installs; 2026 schedule loads | 2026-08-24 | Import + schedule fetch |
| F1DB active release v2026.12.0 | 2026-08-24 | GitHub releases API |

Explicitly NOT yet verified: SignalR incremental feed frames, CarData.z /
Position.z payload formats (documented secondhand), live-window latencies for
any provider, OpenF1 MQTT/WS sponsored transport.
