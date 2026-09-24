# Phase 10.2 — Real-Data Validation

## 17. Acceptance result (stated first)

**BLOCKED.** No real same-session two-driver telemetry pair was obtained, so
the real-data gate is not closed. Nothing below claims otherwise.

What *was* delivered: every tool needed to close it with one command, an
identity guard for the contamination that caused the earlier false
"successes", and fixes for three real bugs in a live API route.

## 1. Objective

Run a genuine two-driver lap pair through raw provider → canonical mapper →
10.1B → 10.1C → 10.2, with zero fabrication.

## 2. Repository state

- Local HEAD at start: `8ab2399`. Tree clean. 10.1B, 10.1C and 10.2 present;
  404 passed / 4 skipped; frontend 51/51; ESLint 0 errors.
- **GitHub `origin/main` was still `f897894`**: none of the Phase 9 →
  10.2 commits had been pushed. They exist only in the delivered bundles.

## 3. Providers investigated

| Source | Real multi-driver car telemetry? | Usable here? | Evidence |
|---|---|---|---|
| OpenF1 REST, direct from sandbox | yes | **no** | `HTTP 403`, `x-deny-reason: host_not_allowed` (sandbox allowlist) |
| OpenF1 via web-fetch tool | yes | **no** | Every never-before-requested URL → `401`. Only previously fetched URLs return their old cached bodies |
| SignalR / F1 live timing (`CarData.z`) | yes | **no** | Repo decoder is marked "ASSUMED format until first capture": it parses space-separated CSV and emits no driver number. Not a verified mapper; real data through it would not be a production-path test |
| FastF1 | yes | no | Needs livetiming hosts (not allowlisted) and the unverified SignalR format above |
| Jolpica | no car telemetry | n/a | lap/results data only |
| Existing fixtures | one driver only | partial | `real-openf1-9159` = driver 55 stationary warm-up + 2 isolated samples |

**Why OpenF1 returned 401:** OpenF1 blocks **all** unauthenticated access,
past sessions included, while any F1 session is live. A public GitHub issue
quotes the response body: "Live F1 session in progress. Global API access
(including past sessions) is restricted to authenticated users until the
session ends." This validation ran on Thu 24 Sep 2026, Azerbaijan GP
practice day (FP1/FP2; qualifying Fri 25, race Sat 26). The blocker is
temporary.

## Cross-driver contamination (Section 3)

Proven, not suspected. Earlier requests for driver 1 / session 11353 and
driver 16 were answered with the byte-identical driver-55 / session-9159
body, and the fetch metadata's `destination_url` showed the substitution.
After the 401 policy began, the exact driver-55 URL that used to "work"
also returned 401, so the earlier bodies were a stale cache.

Nothing in the OpenF1 layer compared request against response. Added
`app/providers/openf1/real_data.py::validate_rows_identity`: every row must
carry the requested `driver_number` and `session_key`. One wrong or
unidentifiable row rejects the whole response. It is tested against the
exact observed contamination.

## 4–8. Dataset, driver pair, lap selection, provenance, coverage

Not obtained (see 17). Prepared instead:

- **Lap selection rule** (`select_reference_lap`): an explicit lap is used
  only if complete and not pit-out (otherwise error, never substituted);
  by default, the fastest complete non-pit-out lap.
- **Coverage report** (`app/analysis/telemetry_integrity.py`): samples,
  first/last/duration, largest gap, gaps above the 10.1B `MAX_GAP_S`
  (imported, not redefined), monotonicity, duplicates, speed validity and
  range, per-field availability. It measures only; it never sorts or repairs.

## 9–12. Distance, sync, delta, numerical checks — the gate as built

`backend/tests/test_real_pair_acceptance.py` (skips until a real fixture
exists; never falls back to synthetic data):

- identity re-validated from the raw files; two different drivers, one session
- telemetry covers each official lap window to within `MAX_GAP_S`; provenance class B
- 10.1B total distance equals an **independent** trapezoid over the raw rows
- **precision:** at x = 0.25, 0.5, 0.75, 1.0, both delta paths (10.1C
  `delta_at` and 10.2 per-sample) equal an independent from-raw-rows
  recomputation to 1e-6 s; where the independent code finds no data,
  both engine paths must return `None`
- plausibility (not precision): finish delta vs official lap-time difference
- max gain/loss equal the extrema of the delta arrays; sign convention holds;
  no GAINING/LOSING segment spans a point without data

**Proven to discriminate** on a throwaway synthetic pair in `/tmp` (deleted
after each run, never committed, not evidence of anything about F1). The
clean run passes. Each of these fails it: a 10 ms delta bias, a 0.1% clock
error, a 0.1% integration bias, one contaminated row, and a 5 s
official-time error.

## 13. API validation — three bugs found and fixed

`GET /api/v1/sessions/{sid}/telemetry/compare` was:

1. **Unreachable.** `/telemetry/{driver_number}` was registered first, so
   `compare` was parsed as a driver number and every request got a 422.
   Fixed with Starlette's `{driver_number:int}` convertor, a one-token change.
2. **Would crash if reached.** It called `.json()` on a server-side
   `JSONResponse`. Fixed to decode `resp.body`.
3. **Claimed an alignment it never computed.** It returned
   `mode=normalized_lap_progress, valid=true`, but `?lap=` only narrows each
   driver's own time window. Now `mode=lap_time_window, valid=false` with a
   note, and `docs/TELEMETRY_API.md` is corrected to match.

No frontend code or test consumed the route. Each fix was proven red-green:
reverting it makes `tests/test_telemetry_compare_honesty.py` fail.
Distance-synchronized comparison (10.1C) is still **not routed**. No new API
contract was invented in this phase.

Known, not fixed: `get_telemetry(?lap=)` invents a 3-minute window when a
lap has no `duration_s`. This is live behaviour for in-progress laps and is
flagged for a decision, not silently changed.

## 14. Database lineage

The acceptance path is raw fixture → mapper → engines. It bypasses Postgres
legitimately: the engines are pure computation, and 10.1A's E2E test
already proves telemetry → Postgres → API lineage.

## 15. Tests (fresh run, this session)

- Backend: **427 passed, 14 skipped**. Skipped = 4 pre-existing + 10 gated
  real-pair tests.
- Added: 13 identity/selection/integrity tests, 7 script plumbing tests, 1
  route honesty test, and 2 Section 16 regression tests (float tolerance at
  x=1.0; both drivers incomplete).
- Red-green verified: the three route fixes, the b521a32 coverage fix, and
  the float tolerance.
- Mutation-checked: the identity guard and lap-selection rule.
- Ruff: `app/` baseline 218 unchanged; `api/__init__.py` 12 before, 12
  after; changed files clean. Frontend: build OK, 51/51, 0 ESLint errors.

## Review notes (doubt-driven, **degraded**)

This was a self-review. No fresh-context subagent can be spawned from this
environment, and cross-model review (Gemini/Codex CLI) was not run. It is
offered for you to run locally.

It caught a flaw in my own first fix. A "data-derived" finish tolerance
came out *looser* (4.3 s) than the flat 4 s it replaced, and let a 1.5 s
engine bias through. It was replaced by independent recomputation, which
then also exposed that the check covered only one of the two delta paths.
Both are fixed.

## 16. Known limitations

- The real-data gate is not closed.
- The SignalR `CarData.z` decoder is unverified against real data.
- `/compare` is honest now but still not distance-aligned. Routing 10.1C
  is future work.
- There is no noise-calibrated STABLE threshold (needs real pairs).

## How to close the gate (run locally, outside a live F1 session)

```bash
cd backend
python ../scripts/fetch_real_driver_pair.py \
  --session-key 9161 --driver-a 55 --driver-b 63 \
  --lap-length-m <official circuit length, metres> \
  --lap-length-source "<citation for that length>"
.venv/bin/python -m pytest tests/test_real_pair_acceptance.py -v
```

Session 9161 (2023 Singapore GP qualifying) is a suggestion: a real lap
record for driver 63 there was already verified. **Look up the official
circuit length yourself.** This document deliberately does not supply
one. The script aborts on any identity mismatch, missing session,
pit-out-only driver or empty telemetry window. With a 401, it explains
the live-session lock. The artifact is `scripts/fixtures/real-openf1-pair/`
(raw rows + `meta.json`). When all 10 gated tests pass, the status can move
to REAL-DATA VALIDATED.
