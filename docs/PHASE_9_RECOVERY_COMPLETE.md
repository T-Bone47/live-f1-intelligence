# Phase 9 Recovery — Complete

Closes out the partial-recovery state documented in `README_SNAPSHOT.md`
after the sandbox reset. Both missing patch ranges it named are now
reconstructed, verified, and committed on top of the `f897894` baseline as
seven atomic commits. This doc records what was actually done and how each
piece was checked against the real repository, not assumed from the prior
session's docs — several details below turned out more precise, or slightly
different, than the surviving docs implied.

## What was recovered

**Weather field contract** (`431497b`). Backend `WeatherEngine.latest()` was
emitting a bare `wind_speed` key and dropping `wind_direction_deg` entirely
despite tracking it internally; frontend read `wind_speed_kph`/`rain_pct`,
neither of which the backend has ever sent. Fixed on both sides; the
`wind_speed_mps` unit was independently checked against official FIA session
weather reports (m/s) rather than taken on the prior session's word.
`tyres_2` — the other half of this same patch range — was checked and
confirmed already correct in this snapshot, exactly as `README_SNAPSHOT.md`
claimed. No work needed there.

**Two F821 undefined-name bugs** (`49d0af2`). `app/ingest/normalize.py`
raised a bare `NormalizationError` with no import in scope in two fallback
branches; `app/storage/db.py`'s `insert_event` called bare `json.loads` when
only `_json` was imported in that method. Both are real, traced to their
exact lines, and covered by new regression tests (`tests/test_normalize.py`)
that fail with the real `NameError` before the fix.

**`snap.profile` dead render gate** (`bdd4683`). `PracticeClassification`
and `QualifyingCutLine` gated their entire render on a field the backend has
never sent. The real field, `session_type`, is title-cased
(`"Practice"`/`"Qualifying"`) — a naive rename alone would still have been
broken. Confirmed against the backend enum and an existing correct precedent
elsewhere in the codebase (`App.tsx`'s session-type detection).

**`DataFreshness` showing LIVE during replay** (`181c9cc`). REPLAY status
shared the exact hardcoded `ageMs` as LIVE, with no way for the freshness
indicator to know the actual mode. Added a `mode` prop; LIVE text/styling
now require `mode === "LIVE"`.

**`serve_realtime.py` regression + `PersistenceSubscriber` wiring**
(`485f481`) — the start of Phase 10.1A. `build_runtime()` referenced a
`server` variable that was never assigned and never called the `create_app`
it imported; this would crash on startup, live or replay. Fixed using the
exact pattern already in `scripts/load_test_ws.py`. Separately,
`PersistenceSubscriber` was fully built but never attached to the envelope
bus anywhere — wired per `docs/PHASE_10_TELEMETRY_REPLAY_ARCHITECTURE.md`
section 4/11. Both verified against a real, locally-installed Postgres
instance: booted the actual gateway against `scripts/fixtures/mini-recording`
and hit it with real HTTP requests; separately fed schema-valid `SessionInfo`
and `Lap` envelopes straight through the subscriber and confirmed real rows
in `sessions`, `laps`, and `events` afterward. The mini-recording fixture
itself turned out stale against the current `SessionInfo` model (4 missing
required fields) — a separate, pre-existing fixture-generation issue in
`scripts/_make_mini_recording.py`, not a wiring bug, and out of scope here.

**RTL infrastructure + all 7 component tests** (`f22156c`). Zero component
test coverage existed before this. Added `@testing-library/react` +
`jest-dom` + `user-event` + `jsdom`, set vitest's environment to `jsdom`
(was the vitest default of `node`), and wrote real behavior-level tests for
`TimingTower`, `LapIntelligence`, `PitAnalytics`, `PracticeClassification`,
`QualifyingCutLine`, `TimeDelta`/`TheoreticalLap`, and `WhatChanged`. 51
tests across 9 files, up from 17 across 2.

**Frontend ESLint setup** (`34638d1`). There was none. Added per the exact
spec in `PHASE_9_CODE_QUALITY.md` — flat config, `no-explicit-any` as `warn`
(a real signal, not suppressed), and only `rules-of-hooks`/`exhaustive-deps`
from `eslint-plugin-react-hooks` rather than its full `recommended` (which
would flag this codebase's existing fetch-in-effect pattern as errors).
Fixed all 30 real errors this surfaced.

## One honest discrepancy

`PHASE_9_CODE_QUALITY.md` documented the target lint result as "0 errors,
126 warnings (all `no-explicit-any`)". The real result here is 0 errors, 109
warnings — 105 `no-explicit-any`, and 4 genuine `react-hooks/exhaustive-deps`
findings (`Panels.tsx` x2, `TelemetryLab.tsx`, `TimingTower.tsx`), each
spot-checked and real. `TimingTower.tsx`'s sector-fetch effect depends on
`board.length` rather than `board` itself, which reads as a deliberate
anti-thrash choice — the fetch is already on an 8-second interval regardless,
and depending on the full array would restart that interval on every minor
reorder rather than only on an actual grid change. Left as a warning, not
force-fixed to chase the old count: the rule is `warn` by design for exactly
this reason, and changing the dependency array would be an unrequested
behavior change to a working pattern, not a lint cleanup.

## Verified final state

- Backend: `319 passed, 4 skipped, 0 failed` (was 313/4/0 at the start of
  this recovery).
- Frontend: clean `tsc && vite build`; `51 passed` across `9` test files
  (was 17/2); `npm run lint` → `0 errors, 109 warnings`.
- All of the above run for real in this session, not assumed from prior
  documentation.

## What this does not include

Everything in `README_SNAPSHOT.md`'s two missing-patch ranges is accounted
for. This does not touch anything past "the very start of Phase 10.1A" —
the rest of Phase 10.1A (downsampling tiers, replay-parity evidence beyond
persistence, anything past section 4/11 of
`PHASE_10_TELEMETRY_REPLAY_ARCHITECTURE.md`) is unstarted, by design, per
the master recovery prompt's scope.
