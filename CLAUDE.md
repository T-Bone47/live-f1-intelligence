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
- Phase 10.3: position-based alignment engine built (`app/analysis/track_geometry.py`),
  proven on exact geometry. **Real-data gate armed and waiting for `/location` data.**
- Baseline: backend 454 passed / 10 skipped (5 skips = 10.3 gate awaiting
  data); frontend 51 passed; ESLint 0 errors (109 pre-existing warnings);
  ruff `app/` 218 pre-existing findings. **Never touch pre-existing lint debt
  unasked.** Changed files must be ruff-clean.

## Next step
Run the Phase 10.3 real-data gate (you have network access here; the old
sandbox didn't):
```powershell
cd backend
.\.venv\Scripts\python.exe ..\scripts\fetch_real_driver_pair.py --session-key 9161 --driver-a 55 --driver-b 63 --lap-length-m 4940 --lap-length-source "Wikipedia, 2023 Singapore Grand Prix: course length 4.940 km (Marina Bay 2023-2024 layout)"
.\.venv\Scripts\python.exe -m pytest tests\test_real_pair_position_alignment.py tests\test_real_pair_acceptance.py -v
.\.venv\Scripts\python.exe ..\scripts\audit_real_pair.py
git diff --stat
```
Expected diff: new `driver_*_location.json` + `meta.json` timestamp/version.
Any change to `driver_*_car_data.json` is itself a finding — investigate.
The central claim (position places official S1/S2 lines closer than speed's
4.3 m / 2.0 m) is **falsifiable**: if it fails, report it; do not tune it away.

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
