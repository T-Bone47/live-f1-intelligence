# PHASE 9 — FOUNDATION READINESS REPORT

> 40 commits (`ff7c437`..`HEAD`). Every number below is from a command run
> today, most from a completely fresh rebuild (backend venv deleted and
> reinstalled from nothing, one more time, immediately before writing this).

## 1. Backend test result
**316 passed, 4 skipped, 0 failed.** The 4 skips are all legitimate
(`GEMINI_API_KEY not configured`, `replay requires setup`, `mini recording
fixture not built`) — none are bugs. Confirmed from a completely fresh
`python3 -m venv .venv && pip install -e ".[dev]"`, no manual package
installs.

## 2. Frontend test result
**52 passed, 0 failed**, across 9 files. 17 are the original logic tests
(unaffected by anything this phase touched). 35 are new: React Testing
Library infrastructure didn't exist before this phase (flagged twice
earlier in this conversation as a real gap) — built it, then wrote real
tests for all 7 named components (`LapIntelligence`, `PitAnalytics`,
`PracticeClassification`, `QualifyingCutLine`, `TimeDelta`+`TheoreticalLap`,
`WhatChanged`, `TimingTower`), every one against backend-shaped fixtures
pulled from the actual dataclasses and endpoint handlers, not invented
shapes. Writing these tests found 4 more real bugs that reading the code
alone hadn't caught (see §7).

## 3. Build result
**Clean.** `tsc && vite build` — 0 TypeScript errors, 0 warnings.

## 4. Startup result
App construction verified directly (not just via `TestClient`): 25 routes
registered. Beyond that, actually booted a real `uvicorn` server bound to
a real TCP port and hit it with a real `curl` request — `200 OK`,
`{"status":"ok"}` — then shut it down and confirmed clean lifecycle
logging (startup → shutdown → "Application shutdown complete"). Then ran
the actual documented entrypoint, `scripts/serve_realtime.py`, directly —
found and fixed a real path-construction bug in replay resolution (was
producing `recordings/recordings/...`, a doubled path, in its fallback
branch — see §7). Postgres is confirmed *not* a hard boot blocker: the
pool connects lazily, only inside `/telemetry/{driver}`.

**Not executable in this sandbox, honestly:** `--mode replay` needs a
recording under `recordings/`, which is gitignored by design and doesn't
exist in a fresh clone — confirmed via the corrected, no-longer-doubled
error path. `--mode live` needs OpenF1/SignalR network access this
sandbox's allowlist doesn't have (only GitHub/PyPI/npm are reachable).
Neither has been faked or assumed working.

## 5. Provider status
Full matrix in `docs/PHASE_9_PROVIDER_AUDIT.md`, re-verified fresh this
phase rather than reused. Summary: OpenF1, Jolpica, FastF1 implemented.
SignalR implemented but disabled by default (`signalr_enabled: bool =
False`, confirmed). F1DB deliberately stubbed — real, honest, in-code
comment confirms the upstream repo was checked, not faked; building it is
explicitly greenfield (the 57-section spec), not this phase. Replay
implemented, with the path-doubling bug from §4 fixed. **Nothing has been
live-tested** — this sandbox has no network path to any of the four live
sources, unchanged since the first message in this conversation.

## 6. UX limitation status
All 17 re-checked against HEAD with direct evidence, in
`docs/UX_LIMITATIONS_CURRENT.md`: **11 FIXED, 4 PARTIALLY_FIXED, 2
STILL_OPEN, 0 NOT_REPRODUCIBLE.** One correction made mid-phase and left
visible in that doc rather than quietly overwritten: item 11 (qualifying
UI) was first marked FIXED on the evidence that the component existed and
was wired in — then, while writing its Phase H test, found it gated on a
field (`snap.profile`) that never existed, so it could never render at
all. Fixed and re-verdicted to PARTIALLY_FIXED (it renders now; its
Q1/Q2/Q3 segment detection still has no real backend signal to key off —
documented, not guessed at). The two STILL_OPEN items (circuit geometry,
replay controls) both need new frontend surface area, not bug fixes —
correctly out of scope for a stabilization phase.

## 7. Contract mismatch status
**19 distinct frontend/backend contract mismatches found and fixed across
this conversation's audit work**, all following the same root cause: code
written against assumed field names/shapes never checked against what the
backend actually returns, masked by `any` typing throughout the state
layer so `tsc` couldn't catch any of them. In finding order: `Provenance
Badge`/`ConfidenceBadge` props (4 files) · `LapIntelligence`'s fabricated
per-lap array (real crash risk) · `TimeDelta`/`TheoreticalLap`'s sector
fields · `TimingTower`'s sector-classification field (led to adding real
classification computation server-side) · `tyres_2`'s missing
`compound`/`lap_start`/`lap_end` · three separate weather field/unit
mismatches · `StrategyBoard`'s `pit_loss_estimate_s`/`delta_s` ·
`RCFeed`'s event text and filter categories · `AIConsole`'s async-response
shape (real crash risk on a *successful* answer) · `TelemetryLab`'s
`samples`→`series` (the entire TEL workspace had never rendered a trace)
· `session_type`/`country_code`/`circuit_short_name` never reaching the
snapshot · `App.tsx`'s preset auto-detection (wrong case, and unused
regardless) · `PracticeClassification`/`QualifyingCutLine`'s dead
`snap.profile` gate · `PitAnalytics`'s `stop.ts` (`"Invalid Date"`) ·
`WhatChanged`'s event text and `STRATEGY_DEVIATION` · `DataFreshness`
showing LIVE during replay · `ReplayProvider`'s path doubling · two real
`F821` undefined-name bugs (`NormalizationError` unimported;
`json`/`_json` typo in the core event-persistence path).

Every fix has real verification behind it — a passing test, a fresh
build, or (for the ones with no feasible test target, like the Postgres-
dependent `insert_event` typo) direct code tracing plus a full green
suite confirming no import-time breakage.

## 8. Dead-control status
The 8 workspace nav buttons (TIM/MAP/TEL/STR/TYR/BTL/AI/EVT) were fully
dead — clicking any of them only changed which button *looked* active;
nothing read that state. Fixed: scroll-to-panel wiring across all 6
layout presets. The 6 preset buttons (RACE CMD/QUALI/TELEMETRY/STRATEGY/
DRIVER FOCUS/MINIMAL) were confirmed correctly wired via a type-safe
union the compiler already enforces — never actually broken. `RCFeed`'s
event filter had 2 of 5 categories matching nothing real — fixed.
`PracticeClassification` and `QualifyingCutLine` were arguably a worse
case than a dead button: not unresponsive controls, but entire panels
that could never render under any circumstances — fixed.

## 9. Remaining bugs (found, not fixed)
- `QualifyingCutLine` always shows the Q1 cutoff regardless of actual
  segment — no Q1/Q2/Q3 signal exists anywhere in the backend to fix this
  with a field correction; needs new tracking (§12).
- `events.py` has `"BATTLE_ESCALATED" if False else "BATTLE_SEPARATED"` —
  a dead conditional, always takes the else-branch. Needs understanding
  the intended battle-state-transition logic to fix correctly; flagged
  rather than guessed at.
- 2 remaining `F811` (redefined-while-unused) ruff findings — lower
  severity than the `F821`s fixed in §7, not individually investigated.

## 10. Remaining technical debt
- `analysis/` still has parallel v1/v2 modules (`battles.py`/`battles2.py`,
  `strategy.py`/`strategy2.py`, `tyres.py`/`tyres2.py`) — flagged in the
  very first audit of this conversation, never resolved. Real risk:
  whichever isn't canonical will silently drift.
- ~289 cosmetic ruff findings remain (import order, regex-flag style,
  deprecated typing imports) — categorized in `docs/PHASE_9_CODE_QUALITY.md`,
  deliberately not bulk-fixed (a 223-line auto-fix diff of pure style
  isn't this phase's job).
- 126 frontend `any` warnings, surfaced on purpose (see §7 — every bug
  found was hidden by one of these) rather than cleared.
- 5 pre-existing `npm audit` findings in the vite/vitest/esbuild chain —
  dev-only, would need a major Vite version bump to clear; out of scope.
- `backend/f1_intel_backend.egg-info/` is checked into git (should be
  gitignored) — cosmetic, never addressed.

## 11. What is genuinely ready
The backend is solid: mature, 316 tests deep, dependencies now genuinely
self-sufficient from a documented clean install, and *proven* — not just
argued — to boot and serve real HTTP correctly. The frontend now correctly
consumes essentially every backend contract it touches, verified file by
file across the whole component tree, not sampled. Test coverage now
exists for what was previously the single largest gap (the 7 named
components had zero). Linting exists on both stacks for the first time.
No dead buttons remain. The UI never falsely claims LIVE. This is a
genuinely stable foundation for the product as it exists today — a
single live-or-replay session dashboard.

## 12. What remains greenfield
Unchanged from every report in this conversation: the entire original
57-section spec. Routing (zero router dependency installed), Session
Explorer, driver/team/circuit pages, global search, cross-race
comparison, the LIVE/UPCOMING/HISTORICAL/REPLAY home state machine, F1DB
circuit geometry integration. None of it has been started — every commit
in this phase stabilized what already existed. Also newly scoped this
phase: a frontend replay-controls UI (backend already supports
play/pause/speed), and real Q1/Q2/Q3 qualifying-segment tracking.

---

**Not proceeding into Phase 10 automatically, per the brief.**
