# Phase 10.1A — Telemetry Persistence & Replay Foundation — Complete

Closes the scope defined in the Phase 10.1A recovery prompt: hardening the
persistence wiring from the Phase 9 recovery into a verified, correct,
tested foundation. Ten commits on top of the Phase 9 recovery baseline
(`2af95d9`). Distance synchronization, the lap-comparison endpoint, circuit
geometry, and any new frontend visualization remain untouched, as scoped.

## What reconnaissance found (Sections 3-4)

Read all 12 named architecture docs plus every Phase 10 doc. Two things
worth recording for whoever reads this next:

- The older Phase 0/1 docs (`DATA_MODEL.md`, `REPLAY_ARCHITECTURE.md`)
  describe a materially more ambitious design than what was actually
  built — a two-tier raw+canonical recording format, a Postgres frame
  index, object-storage snapshots, none of which exist. The Phase 10 docs
  and the actual code are what's real; the Phase 0/1 docs are historical
  planning artifacts, not current truth. `DATA_MODEL.md` also still says
  `wind_speed_kph` — superseded by the Phase 9 recovery's `wind_speed_mps`
  fix, independently corroborated by `PHASE_10_DATA_AVAILABILITY.md`'s own
  research.
- `scripts/record_session.py`, `scripts/replay_session.py`, and
  `scripts/live_acceptance.py` already wired `PersistenceSubscriber`
  correctly, and always had — the regression fixed in the Phase 9 recovery
  was specific to `scripts/serve_realtime.py`, the one entrypoint that
  actually serves the live dashboard. This resolves what initially looked
  like a contradiction: `DATA_PIPELINE.md` documents a real prior
  acceptance run (2023 Dutch GP, session 11353, 1M+ events) that couldn't
  have used the always-broken script, and didn't need to.

**A correction, made mid-session and recorded here rather than quietly
fixed**: partway through, `scripts/fixtures/mini-recording` appeared to
only decompress to 1 of its claimed 25 frames, which was reported as a
stale/broken fixture. That was wrong — it was a mistake in the
verification method (a single-shot `ZstdDecompressor().decompress()`
call only recovers the first of several concatenated zstd frames;
`Recorder.write()` produces one frame per call by design, and
`app/providers/replay.py` already reads them back correctly via
`stream_reader()`, which handles concatenation transparently). Re-checked
with the same method the real code uses and confirmed all 25 frames are
present and correct. Neither `Recorder` nor `ReplayProvider` needed a fix.

## What was fixed

**PersistenceSubscriber accounting** (`c52b87e`). `flush()`'s bulk insert
paths used `executemany()`, which cannot `RETURNING` — so `written` always
reported the full attempted batch size, even for rows silently absorbed by
`ON CONFLICT DO NOTHING`. A genuine event-log insert failure was also
counted as written, since the increment sat outside the try/except that
caught it. Fixed via a single multi-row `INSERT ... RETURNING`, counted
through `fetch()`; added a distinct `errors` counter alongside `written`
and `conflicts`.

**Telemetry provenance** (`781431c`). `GET /telemetry/{driver}` derived
its response's `provenance.class` from `hub_active(session_id)` — "is any
hub registered", live or replay, indistinguishably. A replay in progress
would report its correctly-persisted class-B telemetry back as class A.
Checked whether `provider_name` could serve as a live/replay signal
instead and found it inconsistently populated across scripts (one real
example: `record_session.py`'s genuinely live captures set it to
`"openf1"`, the provider name, not the mode) — not safe to key off. Fixed
by reading `provenance_class` from the actual rows being returned instead.

**Replay pause control** (`69eb222`). `POST /replay/{id}/control
action=pause` set `hub._paused` and returned 200 OK; nothing anywhere read
that attribute back. Added `SessionHub.wait_while_paused()`, wired into
the feed loop. Verified via a real endpoint call flipping the real
attribute, and the wait coroutine's actual blocking behavior in isolation
— the only available recording turned out to have no inter-frame gap at
any speed to pause within, checked directly rather than assumed, so a
live timing demo wasn't attempted.

**Missing test coverage** (`5b9202d`). Zero tests existed for the LTTB
downsampling algorithm. Added ordering, edge-case, and — the actual reason
LTTB exists over naive decimation — spike-survival tests, using synthetic
signals (appropriate for unit-testing the algorithm's own properties; the
real fixture is too small to exercise actual point reduction).

## The end-to-end acceptance test (Section 23)

The primary gate this phase built toward, and the part that took the most
care to get right: Section 21 requires real recorded F1 telemetry for this
specific test, not synthetic. The sandboxed environment can't reach
OpenF1's API from a shell — fetched genuine historical `car_data` (2023
Singapore GP weekend, session_key 9159, driver 55) via web search/fetch
instead, which aren't sandboxed the same way. Built
`scripts/fixtures/real-openf1-9159` (`940601a`) through the project's own
real mapping function (`to_car_sample`) and real `Recorder`, not hand-built
models — checked in the raw API response alongside it so the fixture
rebuilds without a live fetch.

`tests/test_e2e_real_telemetry_acceptance.py` (`f6e400a`) replays it
through `ReplayProvider` → `SessionHub.feed()` — the same path live data
takes — into a real Postgres instance, then checks the REST API against
the database directly: exact row counts (39 telemetry, 40 audit-log, zero
conflicts, zero errors), genuinely ordered timestamps, `provenance_class`
staying B throughout, two specific known-real values (315 km/h at RPM
11141 and 11023) surviving the full round trip intact, and the API's
returned series matching the database exactly, same values, same order,
queried with no active hub for the session at all.

## Verified final state

- Backend: `338 passed, 4 skipped, 0 failed` (was 319/4/0 at the start of
  this phase).
- `ruff check app`: 218 findings, identical before and after this phase's
  work (confirmed via `git archive` diff against the Phase 9 baseline) —
  none of it is new, and it wasn't touched, per this recovery's own
  surgical-fix scope. The 4 new test files added this phase were separately
  linted and fixed to zero findings.
- Frontend: unaffected by this phase, reconfirmed clean (`51 passed`, `0`
  lint errors) rather than assumed.
- Runtime gate: the actual gateway process booted against both the real
  fixture and the original mini-recording, hit with real HTTP requests
  (health, sessions, snapshot, telemetry), shut down gracefully with a
  confirmed flush, multiple times across this phase's work — not
  substituted with an import check.

## What this does not include

Per the recovery prompt's own hard rules and the Phase 10 architecture
doc's "exact implementation order" (item 1 of 6 was this phase; items 2-6
are exactly what's excluded): distance-along-lap derivation, the bulk
per-lap comparison endpoint, centerline/circuit geometry, and any new
frontend telemetry visualization remain untouched and unstarted.
