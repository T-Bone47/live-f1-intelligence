# CLAUDE.md — Live F1 Intelligence

Loaded automatically by Claude Code at session start. It carries context
from the claude.ai sessions that built Phase 9 → 10.3. Keep it current:
update "Current state" and "Next step" whenever a phase lands.

## What this is
Real-time + historical F1 intelligence platform. Backend: Python 3.11,
FastAPI, asyncpg/PostgreSQL, OpenF1 provider. Frontend: React + Vite +
TypeScript (vitest, ESLint flat config). Repo: github.com/T-Bone47/live-f1-intelligence

Phase history and evidence (read on demand, don't re-derive):
@docs/PHASE_10_3_TRACK_GEOMETRY.md
@docs/PHASE_10_2_REAL_DATA_VALIDATION.md

## Current state (update me)
- Phase 10.2: **REAL-DATA VALIDATED (pipeline correctness).** Real pair:
  session 9161 (2023 Singapore Q3), driver 55 Sainz lap 19 (90.984 s, pole)
  vs driver 63 Russell lap 16 (91.056 s). Fixture: `scripts/fixtures/real-openf1-pair/`.
- Phase 10.3: position-based alignment engine built (`app/analysis/track_geometry.py`).
  **Real-data gate RAN 2026-09-25: central claim FAILS at S2.** S1: position
  2.8 m vs speed 4.3 m ✔. S2: position **3.7 m vs speed 2.0 m** ✘, and the
  position S2 delta error is +0.046 s vs speed's −0.007 s. Driver 63 has one
  projection at a 58.7-unit offset (held MEDIUM), and the position-aligned max
  loss jumps to +0.49 s @ x=0.621 (speed: +0.135 s). 13 passed / 1 failed /
  1 skipped. The location fixture (`driver_*_location.json` + meta v2) is
  fetched but **left uncommitted**, because committing it makes HEAD red.
  car_data files are unchanged.
- Additional sources (2026-09-25, docs/DATA_SOURCES.md §2.7–2.8): Blacktop
  (free tier; challenger for results/quali/standings via
  `app/analysis/source_crosscheck.py`) and RapidAPI F1 Live Pulse (20 req per
  ~23 days; quota-guarded fixture recorder only). The Postman link is the
  dead Ergast API, which Jolpica already serves. Both provider flags stay false.
- Baseline (this Windows box, no Postgres/Gemini): backend 503 passed / 14
  skipped / 1 failed (the 10.3 S2 finding, only while the location fixture is
  present; skips: 9 Postgres, 2 Gemini, 2 replay setup, finish NO_DATA).
  Frontend 51 passed; ESLint 0 errors (109 pre-existing warnings); ruff `app/`
  pre-existing findings (jolpica/mapping.py keeps its 4). **Never touch
  pre-existing lint debt unasked.** Changed files must be ruff-clean.

## Next step
1. Investigate the 10.3 S2 failure; do not tune it away. Start with driver 63's
   58.7-unit outlier near x≈0.62 and whether a single held projection moves
   the S2 line; then check whether the reference path (driver 55's own lap)
   cuts a corner that 63 takes wide. Report the finding whatever it is.
2. Optional: `scripts/crosscheck_sources.py --year 2026` after each race weekend.
3. During a live session only: `scripts/record_live_pulse.py sessionInfo timingData`
   to capture real Live Pulse fixtures (each route costs 1 of ~15 left).

## Non-negotiable rules (learned the hard way on this project)
1. **Zero fabrication.** Never invent telemetry, lap times, lengths, or
   provider responses. Missing data → `None` / `Confidence.NONE` / NO_DATA,
   never a guess, clamp, forward-fill, or extrapolation.
2. **Synthetic ≠ real.** Synthetic data is fine for unit tests; never as
   evidence the real pipeline works. Real-data gates skip without real data.
3. **Verify identity.** Every provider response goes through
   `app/providers/openf1/real_data.py::validate_rows_identity`. A cache once
   served driver-55 data for other drivers' requests.
4. **OpenF1 query keys:** use `date>` / `date<` — never `date>=` / `date<=`.
   OpenF1 rebuilds `f"{key}={value}"`, so `date>=` becomes `date>==<ts>` and
   silently matches nothing. (`date>` is actually inclusive `$gte`.)
5. **OpenF1 live lock:** during any live F1 session (−30 min … +30 min) ALL
   unauthenticated requests, historical included, return 401. Wait; don't debug.
6. **One engine per concept.** Reuse `lap_distance` (normalize/sync/delta_t),
   `lap_comparison.compare_traces`, `delta_analysis`, `Confidence`,
   `rollup_trace_confidence`, `LapClass`. New distance *sources* output the
   existing `LapDistanceTrace`; they never re-implement synchronization.
7. **Delta sign:** `delta_t = elapsed_A − elapsed_B`; negative = A ahead. Never flip.
8. **TDD + prove tests can fail.** Red first. Mutation-check key mechanisms
   (break it → a test must fail). A stub test once asserted the *bug*
   (`date>=`) and passed — verify against real behaviour where possible.
9. **Tolerances must be justified**, not tuned. A "data-derived" bound once
   came out looser than the flat one it replaced; prefer independent
   recomputation to 1e-6 over tolerance bands.
10. **Evidence before claims.** Never say "passes"/"validated" without
    running it this session. Report skips and their reasons.
11. **Git:** small logical commits; each commit green on its own; scan
    diffs for secrets/machine paths before committing; never force-push.

## Secrets and new APIs
- API keys go in `backend/.env` (gitignored) and are read via `app/config.py`
  settings. Never commit keys, never print them in logs or test output.
- A new provider must: map through a canonical mapper into `app/core/models`,
  preserve provenance, pass an identity guard, and get real-data evidence
  before it is trusted. Check docs/DATA_SOURCES.md first — don't add a
  provider just because it's easier.

## Commands (Windows, from `backend/`)
```powershell
.\.venv\Scripts\python.exe -m pytest tests -q          # full backend
.\.venv\Scripts\python.exe -m ruff check <changed files>
cd ..\frontend; npm test; npm run build; npm run lint
```
3 tests need Postgres (`TEST_DATABASE_URL`, default
`postgresql://f1intel:f1intel_dev@localhost:5432/f1intel`); they skip cleanly without it.

## Open issues (from real data, Phase 10.2 audit)
1. Slow-corner misalignment (38–46 ms per metre at 78–95 kph) → 10.3 targets this.
2. `Confidence` reflects telemetry integrity, not alignment precision.
3. Segmentation over-fragments on real data (173 segments; 0.001 s threshold
   needs calibration from real position-aligned data).
4. Both real traces end at x≈0.98 of the cited length → finish is NO_DATA.
5. `/telemetry/compare` is honest but still not distance-aligned (10.1C/10.3 not routed).
6. `get_telemetry(?lap=)` invents a 3-minute window when a lap has no duration — flagged, not changed.
7. SignalR `CarData.z` decoder is unverified ("ASSUMED format").

## Roadmap after 10.3
10.1C/10.3 API routing → corner/sector intelligence → replay clock/seek →
telemetry visualization → race/strategy replay → qualifying Q1/Q2/Q3 →
historical explorer → session state machine → production hardening.
