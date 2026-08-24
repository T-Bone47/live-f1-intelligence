# TECHNICAL_RISKS.md

| | |
|---|---|
| Status | Phase 0 risk register — reviewed at each phase gate |

Severity: impact × likelihood, 1–3 each. Owner = role.

---

## R1 — Upstream auth posture changes (direct feed)  `Sev: HIGH (3×3)`

The signalrcore endpoint currently accepts token-less connections (verified
via f1-dash production and independent protocol analysis, June 2026), but
FastF1 documents F1TV-account auth as required. F1 can enforce auth at any
time without notice.

**Mitigation**
1. Pluggable auth in LiveTimingProvider from day one (none / bearer-token /
   F1TV-login-refresh paths).
2. OpenF1 sponsor tier (€9.90/mo) as hot fallback — same canonical interface,
   config switch only.
3. Self-hostable OpenF1 ingest stack as last resort.
4. Auth-probe check in CI/monitoring that alerts the moment token-less access
   breaks.

## R2 — Source shutdown or legal pressure  `Sev: HIGH (3×2)`

All sources are unofficial fan/community infrastructure; any could vanish
(OpenF1 already moved live data behind payment citing sustainability).

**Mitigation**: provider abstraction (no vendor coupling); own raw+canonical
recordings of every session (our archive is immune to upstream loss);
non-commercial posture + takedown readiness (DATA_SOURCES.md §9); multi-source
capability matrix maintained.

## R3 — Feed format drift (e.g., new SignalR/topic changes)  `Sev: MED (2×2)`

Mid-2026 migration to `/signalrcore` proves drift is real. Topic payloads may
change field-wise between seasons.

**Mitigation**: normalizer isolates all parsing; contract tests on recorded
fixtures per season; raw tier enables post-hoc re-parse; tolerant enum mapping
(`*_UNKNOWN` + warn); version-stamped derived data for re-runs.

## R4 — Connection instability / silent stalls  `Sev: MED (2×2)`

Observed ~2 h server-side disconnects; silent no-data periods occur.

**Mitigation**: heartbeat watchdogs (forced resync on silence >N s); snapshot
resync on reconnect; explicit `provider.data_gap` events surfaced in UI;
supervised reconnect with backoff+jitter; chaos tests (kill -9) in Phase 4.

## R5 — Rate limits / bans (polling sources)  `Sev: LOW-MED (2×1)`

OpenF1 free 3 req/s & 30 rpm; Jolpica 4 req/s & 500/hr; aggressive polling
risks IP bans during race peaks.

**Mitigation**: subscription-first design (never poll what we can subscribe
to); token buckets client-side; historical backfill off-peak with caching;
Jolpica nightly sync only.

## R6 — Latency misrepresentation  `Sev: MED (2×2)` *(integrity risk)*

Claiming "real-time" without proof violates project rule 13.

**Mitigation**: measure p50/p95 source→client continuously (pipeline.health +
per-event wall-ts deltas); UI shows measured freshness age, not marketing
claims; OpenF1 path labeled ~3 s until our own numbers exist.

## R7 — Data quality: gaps, deletions, conflicts  `Sev: MED (2×2)`

Deleted lap times arrive late via RCM; feed gaps conflict with recomputation.

**Mitigation**: mutable laps w/ tombstones; conflict detection storing both
feed vs. computed values; "data gap" first-class state; validation suite vs.
FastF1/Jolpica cross-checks each phase.

## R8 — LLM hallucination / grounding failure  `Sev: HIGH if uncontrolled (3×1)`

**Mitigation**: architecture makes it structurally hard — packs only,
structured claims with mandatory evidence refs, numeric equality checks against
pack values, retry-once then deterministic fallback text, eval-gate ≥95%
grounding pass in CI. AI output always class-E-labeled.

## R9 — Cost overrun (LLM)  `Sev: LOW (2×1)`

**Mitigation**: event-driven triggers only, cooldowns, pack size caps, model
tiering, hard budgets w/ graceful degradation to digests.

## R10 — Scope creep / over-engineering  `Sev: MED (2×2)`

F1 data projects attract feature sprawl (and the charter forbids it).

**Mitigation**: MVP definition locked in PROJECT_SPEC.md §6; phase gates;
DECISIONS.md records every deferred idea with rationale; roadmap explicitly
postpones k8s/Kafka/ClickHouse/frontend-product until their phases.

## R11 — Dev environment friction (Windows + OneDrive)  `Sev: LOW-MED (2×1)`

Current working directory lives inside OneDrive-synced Documents; file locks
on `.venv`/`node_modules`/postgres data dirs cause flaky builds. ADDITIONALLY
(Phase 1.5 observed): Windows temp cleaning deleted parts of the portable
PostgreSQL tree while it was running.

**Mitigation**: recommend relocating repo outside OneDrive; portable Postgres
binaries now live in project-local ignored dir (`.local-pg/`), data dir stays
in temp — revisit if cleaner purges recur.

## R13 — SignalR token-less access revoked  `Sev: HIGH impact, UNKNOWN timing`

Verified working 2026-08-24 without credentials, but FastF1 documents F1TV
auth and community history shows the posture flips without notice.

**Mitigation**: pluggable bearer-token auth in `SignalRClient`; provider
disabled by default (`SIGNALR_ENABLED=false`); failover chain demotes to
OpenF1 automatically; probe script doubles as an auth-watchdog check.

## R14 — SignalR protocol/format drift  `Sev: MED (2×2)`

Incremental frame shapes and CarData.z/Position.z encodings are ASSUMED
(documented secondhand) until first capture.

**Mitigation**: parsing isolated in `protocol.py`; malformed frames skipped +
counted; first live capture must be diffed against assumptions before any
consumer trusts those channels (capability `assumed` notes enforce this).

## R15 — FastF1/Jolpica upstream changes  `Sev: LOW (2×1)`

FastF1 DataFrame schemas and Jolpica limits evolve.

**Mitigation**: FastF1 adapter duck-typed + offline tests; Jolpica client
conservative defaults (2 rps / 240 rpm) with Retry-After honoring; both are
class-B-only so live paths are unaffected by their breakage.

## R16 — Reconciliation conflicts between providers  `Sev: LOW-MED (2×1)`

Two sources may disagree on the same fact (e.g., lap time X vs Y).

**Mitigation**: policy NEVER merges values; primary wins, challenger retained
with provenance; CONFLICT resolutions surfaced via quality metrics for review
(`app/core/source_policy.py`, unit-tested).

## R12 — Team-radio/audio licensing  `Sev: LOW (2×1)`

Team radio audio URLs are copyrighted content.

**Mitigation**: MVP stores references only (no redistribution); transcription
feature (Phase 7 experiment) treats transcripts as internal derived data; no
audio playback beyond linking until licensing review.

## Monitoring plan

Every risk above maps to a metric/alert by end of Phase 4: provider health,
auth-probe status, pipeline lag, gap counter, rate-limit headroom, LLM budget
& grounding-failure counter, recording continuity checker (expected sessions
archived?).
