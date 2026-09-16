# README — SNAPSHOT STATE (development stopped on request)

This zip is a snapshot of `live-f1-intelligence` at the exact moment
development was stopped, mid-way through recovering from a **sandbox
reset** that happened during Phase 10.1A (telemetry persistence wiring).
It is **not** the complete state that existed before the reset, and it
is **not** a finished deliverable. Read this fully before assuming
anything about what's in here.

## What actually happened

Across a long conversation, real code changes were made to this repo in
phases (a foundation audit and hardening pass — "Phase 9" — followed by
telemetry-replay research and architecture — "Phase 10.0" — followed by
the start of wiring real telemetry persistence — "Phase 10.1A"). None of
this was ever pushed to GitHub (no push access existed at any point) —
every commit only ever existed in a local, ephemeral sandbox clone.

Partway through Phase 10.1A, that sandbox was reset. The local clone,
all its commit history, and a scratch verification script were lost.
The **only** things that survived the reset were files already delivered
to you earlier as downloadable artifacts (patch files and markdown
reports) — because those live in a separate, more persistent location
than the sandbox's own working directory.

## What's actually in this zip right now

- A fresh clone of the real repo, with **20 commits reconstructed** on
  top of the original baseline, by re-applying the patch files that
  survived, plus manually redoing one fix (the `tyres_2` intelligence
  pack fix) that had to be reconstructed from documentation because its
  patch file didn't survive either.
- `docs/` now contains **all 10 of the final capstone reports** that
  *did* survive intact: `PHASE_9_FOUNDATION_READINESS_REPORT.md`,
  `PHASE_9_PROVIDER_AUDIT.md`, `PHASE_9_CODE_QUALITY.md`,
  `UX_LIMITATIONS_CURRENT.md`, `CLAUDE_CURRENT_STATE_AUDIT.md`, and all
  5 `PHASE_10_*.md` architecture/research documents. **These describe
  the full, complete state of everything that was developed across the
  whole session** — including fixes whose actual code changes are
  currently missing from this snapshot (see below). They are the most
  reliable record of what was actually done and why.

## What is known to be missing from this snapshot

Two patch ranges never made it into the surviving output directory and
have not yet been reconstructed:

- **Most of the original patches 0012–0017**: a set of real weather-data
  bug fixes (`wind_speed_kph` never existed — real field is
  `wind_speed_mps`, unit previously unconfirmed, now confirmed m/s;
  `wind_direction_deg` was tracked internally but never exposed;
  `rain_pct` never existed — `rainfall` is a boolean, not a percentage)
  and the corresponding `TyreTimeline.tsx` frontend field-name fix. The
  `tyres_2` half of this range **has** been redone in this snapshot; the
  weather half has not.
- **Patches 0025–0042**: everything from the UX-limitations recheck
  onward — `PracticeClassification`/`QualifyingCutLine`'s dead
  `snap.profile` gate fix, the React Testing Library infrastructure and
  all 7 component test files (`TimingTower`, `LapIntelligence`,
  `PitAnalytics`, `PracticeClassification`, `QualifyingCutLine`,
  `TimeDelta`/`TheoreticalLap`, `WhatChanged`), the `DataFreshness`
  replay-mislabeling fix, the frontend ESLint setup, two real `F821`
  backend bug fixes, and the very start of Phase 10.1A's persistence
  wiring (a regression fix to `scripts/serve_realtime.py`, plus
  attaching `PersistenceSubscriber` to the envelope bus). **None of
  this is in the current code** — only described in the docs above.

Exact technical detail for every one of these — root cause, real field
names, exact fix — is in `docs/PHASE_9_FOUNDATION_READINESS_REPORT.md`
§7 and the relevant commit-message-style descriptions throughout this
conversation's history. Nothing here was lost from documentation, only
from the working tree.

## How to verify the current (partial) state yourself

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests -q
# Expect fewer passing tests than the 316 documented as the full-session
# final count in PHASE_9_FOUNDATION_READINESS_REPORT.md, since several
# fixes and their tests (see above) are not present in this snapshot.

cd ../frontend
npm install && npm run build && npm test
# The build should still be clean; several bug fixes and all component
# tests described in the reports above are not present here.
```

## If picking this back up

The fastest path to the fully-reconstructed state is not to start over —
it's to redo exactly the two missing ranges above, using the capstone
reports as the spec, verifying each fix with real tests the same way
every other fix in this session was verified (not assumed). That work
was in progress when development was stopped on request.
