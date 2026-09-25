# CLAUDE.md — Live F1 Intelligence

Loaded automatically by Claude Code at session start. It is the handoff
between sessions: keep "Current state" and "Next steps" true whenever a
phase lands. Detailed evidence lives in the docs below; read on demand,
don't re-derive.

@docs/PHASE_10_6_FRONTEND_EVIDENCE_WORKBENCH.md
@docs/PHASE_10_5_EVIDENCE_API.md
@docs/RACEWISE_EVIDENCE_CONTRACT.md
@docs/PHASE_10_4_TIME_LOSS_ATTRIBUTION.md

## What this is
The real-time and historical F1 intelligence platform. Repo:
github.com/T-Bone47/live-f1-intelligence (branch `main`).
- **Backend:** Python 3.11, FastAPI, asyncpg/PostgreSQL. Providers: OpenF1
  (primary), SignalR, FastF1, Jolpica, plus Blacktop and RapidAPI Live Pulse
  (both off).
- **Frontend:** React, Vite and TypeScript (vitest, ESLint flat config).
- **Role vs RaceWise:** Live F1 Intelligence (LFI) is the **evidence
  engine**: it measures, synchronizes and attributes. **RaceWise** (a
  separate codebase, not in this repo) is the **reasoning engine**. LFI
  never reasons or concludes, and adds no LLM for that.

## Setup from a fresh clone (Windows)
```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" ruff
# API keys: create backend\.env yourself (gitignored) - see "Secrets" below
cd ..\frontend; npm ci
# Postgres for DB tests (throwaway container on :5432):
docker run -d --rm --name f1intel-test-pg -e POSTGRES_USER=f1intel -e POSTGRES_PASSWORD=f1intel_dev -e POSTGRES_DB=f1intel -p 5432:5432 postgres:16
```

## Commands (from `backend/`)
```powershell
.\.venv\Scripts\python.exe -m pytest tests -q          # full backend
.\.venv\Scripts\python.exe -m ruff check <changed files>
..\scripts\attribution_report.py / evidence_report.py  # regenerate locked evidence (run with the venv python)
..\scripts\bench_attribution.py / bench_evidence.py    # performance
..\scripts\serve_evidence_dev.py   # real pair -> own DB f1intel_evidence_dev, API on :8000
cd ..\frontend; npm test; npm run build; npm run lint
npm run dev                         # /evidence = Phase 10.6 Evidence Workbench
```
On this machine the default parallel vitest run can exhaust RAM (tinypool
"heap out of memory"); `npx vitest run --no-file-parallelism` is reliable.
DB tests use `TEST_DATABASE_URL` (default
`postgresql://f1intel:f1intel_dev@localhost:5432/f1intel`). Without
Postgres they skip cleanly (about 14 tests).

## Architecture (analysis path)
```
provider rows -> identity guard (app/providers/openf1/real_data.py)
  -> canonical models (app/core/models: Lap, TelemetryCarSample)
  -> 10.1B app/analysis/lap_distance.py   distance axis, sync, delta_t
  -> 10.1C app/analysis/lap_comparison.py driver A/B comparison
  -> 10.2  app/analysis/delta_analysis.py DeltaSample curve (+fine segments)
  -> 10.4  app/analysis/attribution.py (+ attribution_signals.py)  time-loss attribution
  -> 10.5  app/evidence/ (schema.py, lap_comparison.py)             evidence_v1 contract
  -> API   app/api/__init__.py
```

**Routes added in Phase 10:**
- `GET /api/v1/sessions/{sid}/evidence/lap-comparison`: evidence_v1, the
  stable contract for RaceWise and the UI.
- `GET /api/v1/sessions/{sid}/attribution`: the unversioned 10.4 report,
  for internal inspection only.

Both require `driver_a, lap_a, driver_b, lap_b, lap_length_m,
lap_length_source`. There is no circuit geometry, so a lap length is never
invented.

## Current state (2026-09-26)
- **10.2: REAL-DATA VALIDATED** on the real pair (session 9161, 2023
  Singapore Q). #55 lap 19 (90.984 s) vs #63 lap 16 (91.056 s). Fixture:
  `scripts/fixtures/real-openf1-pair/`.
- **10.3** (position alignment, `track_geometry.py`): **real-data gate
  FAILS at S2.** Position places the S2 line 3.7 m apart vs speed's 2.0 m;
  S1 improves (2.8 vs 4.3 m). The `/location` fixture
  (`driver_*_location.json` plus meta v2) is fetched locally but
  **deliberately uncommitted**, because committing it turns HEAD red.
  Nothing downstream depends on 10.3.
- **10.4 COMPLETE** (`attribution-1.1.0`):
  - Segments run straight to straight: 12 on the real pair, vs 10.2's 173.
  - Significance band = E·|Δ(1/v)| + (D+W)·max(1/v) + 1 ms:
    - E = misalignment measured at the official sector lines (4.308 m on
      the real pair);
    - D = E (PROVISIONAL);
    - W = a derived speed-quantization walk.
  - Real pair: **no segment significant**. Resolvable control-input
    differences (brake onsets, 2nd vs 3rd gear) are reported as temporal
    associations.
  - 19/19 mutations killed.
- **10.5 COMPLETE** (`evidence_v1`, builder `evidence-builder-1.0.0`):
  - A pure restructure of 10.4, with floats unrounded.
  - Strict, fail-closed pydantic validation.
  - Content-addressed ids (`ev1_…`, `…:g{start}-{end}`, `…:S{n}`).
  - Canonical JSON bytes.
  - The builder maps only `SUPPORTED_ATTRIBUTION_VERSIONS`, so a new 10.4
    version fails closed until reviewed.
  - Locked goldens: `docs/evidence/evidence_v1_singapore.json` and
    `evidence_v1.schema.json`.
  - 14/14 source mutations killed.
- **10.6 COMPLETE** (Evidence Workbench, `/evidence`, frontend only):
  - Consumes `evidence_v1` only (`frontend/src/evidence/`); no analysis in
    the browser. Δt is drawn at segment boundaries only (chords labelled
    "not a measured curve"), each segment with its `inherited_gap ± band`.
  - Telemetry drill-down only on click, RAW, via `telemetry_references`,
    labelled not distance-aligned.
  - Design system: `design-system/live-f1-intelligence/MASTER.md`.
  - 114 new tests on the real golden; 11/11 mutations killed; verified at
    375/768/1024/1440/1920 against the real API.
  - RaceWise seam present but disabled (`VITE_RACEWISE_ENABLED`).
- **Additional sources** (docs/DATA_SOURCES.md §2.7–2.8):
  - Blacktop, free tier: a challenger for results and standings via
    `app/analysis/source_crosscheck.py` and `scripts/crosscheck_sources.py`.
  - RapidAPI Live Pulse: 20 requests per ~23 days; a quota-guarded fixture
    recorder only.
  - The Ergast Postman API is dead; Jolpica serves it.
  - Provider flags stay false.
- **Test baseline:** see "Baseline" at the end of this file.

## Next steps
1. **Stored sessions/laps listing route** (backend, read-only) so the
   workbench can offer pickers instead of typed ids. Then the RaceWise
   integration contract, which unlocks the disabled hand-off button.
2. **Calibrate D and E**, which needs more real pairs
   (`scripts/fetch_real_driver_pair.py`, run outside live sessions).
3. **Investigate the 10.3 S2 failure.** Do not tune it away. Start with #63's
   58.7-unit outlier near x≈0.62, then check whether #55's reference line
   cuts a corner that #63 takes wide.
4. **Optional:** `scripts/crosscheck_sources.py --year 2026` after each
   race weekend.
5. **Live session only:** `scripts/record_live_pulse.py sessionInfo timingData`
   (each route costs 1 of about 15 remaining requests).

## Non-negotiable rules (learned the hard way on this project)
1. **Zero fabrication.** Missing data → `None` / `Confidence.NONE` /
   NO_DATA / class F, never a guess, clamp, forward-fill or extrapolation.
   No apex, corner name or DRS meaning without verified evidence.
2. **Synthetic ≠ real.** Synthetic data (`tests/synthetic_lap.py`) is for
   unit tests only. Real-data gates skip without real data.
3. **Verify identity.** Every provider response goes through
   `validate_rows_identity`; evidence also guards sample and lap identity. A
   cache once served driver-55 data for other drivers' requests.
4. **OpenF1 query keys:** use `date>` / `date<`, never `date>=`
   (it becomes `date>==…` and matches nothing). Likewise, Blacktop silently
   ignores `season=`; use `year=`.
5. **OpenF1 live lock:** during a live session (−30 min … +30 min) every
   unauthenticated request returns 401. Wait; don't debug.
6. **One engine per concept.** Reuse `lap_distance`, `compare_traces`,
   `delta_analysis`, `attribution`, `Confidence` and `SegmentKind`.
   Evidence restructures; it never recomputes.
7. **Delta sign:** `delta_t = elapsed_A − elapsed_B`; negative = A ahead.
   Never flip it.
8. **TDD, and prove tests can fail:** red first, then mutation-check the
   key mechanisms.
9. **Tolerances must be justified**, not tuned: measured, derived, or
   labelled PROVISIONAL.
10. **Evidence before claims.** Never say "passes" without running it this
    session. Report skips and their reasons.
11. **Association ≠ causation.** Only `TEMPORAL_ASSOCIATION` exists; LFI
    never states a cause.
12. **Git:** small logical commits, each green on its own. Scan diffs for
    secrets and machine paths. Never force-push.

## Secrets and new APIs
- Keys live in `backend/.env` (gitignored) and are read via
  `app/config.py`: `BLACKTOP_API_KEY`, `F1_LIVE_PULSE_RAPIDAPI_KEY`,
  `RAPIDAPI_KEY`. Never commit or print them. The Blacktop and RapidAPI
  keys appeared in an earlier chat and **should be rotated**.
- A new provider must:
  - go through a canonical mapper;
  - preserve provenance;
  - pass an identity guard;
  - have real-data evidence before it is trusted.

  Check docs/DATA_SOURCES.md first.

## Pitfalls on this machine/repo
- `core.autocrlf=true`: `docs/evidence/*.json` is marked `-text` in
  `.gitattributes`. Keep it that way, or the golden byte tests break on
  checkout.
- The ECC "GateGuard" hook asks for facts (callers, data, instruction)
  before the first Write/Edit/Bash on each file. State them and retry.
- Never touch pre-existing lint debt unasked (`ruff app/` has pre-existing
  findings; `jolpica/mapping.py` keeps 4, ESLint has 109 warnings). Changed
  files must be ruff-clean.

## Open issues
1. `Confidence` reflects telemetry integrity, not alignment; alignment
   precision is carried separately as `uncertainty_s`.
2. Both real traces end at x≈0.98, so the finish and S3 engine values are
   NO_DATA.
3. `/telemetry/compare` is honest but not distance-aligned. Use
   `/evidence/lap-comparison` for aligned comparison.
4. `get_telemetry(?lap=)` invents a 3-minute window when a lap has no
   duration. This is flagged, not changed; the new routes refuse such laps.
5. The SignalR `CarData.z` decoder is unverified ("ASSUMED format").
6. Pool-per-request DB access costs about 80 ms per API call (API-wide
   convention).

## Roadmap
~~10.6 evidence workbench~~ → 11.x strategy / battles / tyres / predictive
intelligence → replay clock/seek → qualifying Q1/Q2/Q3 → historical
explorer → session state machine → production hardening.

## Baseline (verified 2026-09-25 at HEAD, fresh checkout, Postgres 16 up)
- **Backend:** 739 passed, 10 skipped.
  - 5 skips are the 10.3 gate waiting for the uncommitted location
    fixture; with those files present, the S2 check FAILS as documented.
  - The other 5: 2 need a Gemini key, 2 need replay/recording setup, and
    1 is the finish NO_DATA check.
- **Frontend (2026-09-26, after 10.6):** 165 passed (51 + 114 evidence),
  build OK, tsc OK, ESLint 0 errors (109 pre-existing warnings).
- **Every commit** of Phases 10.4 and 10.5 was verified green on its own.
