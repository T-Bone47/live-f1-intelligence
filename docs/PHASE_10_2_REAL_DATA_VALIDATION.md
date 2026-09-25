# Phase 10.2 — Real-Data Validation

## 17. Acceptance result (stated first)

**REAL-DATA VALIDATED — pipeline correctness.** A genuine same-session
two-driver pair ran through raw OpenF1 → canonical mapper → 10.1B → 10.1C
→ 10.2. The gate result was 9 passed, 1 skipped, both on the Windows
machine that fetched the data and when reproduced here. The skipped
check (finish plausibility) cannot execute, because both real traces end
short of the cited lap length (see "Real pair results").

This validates that the pipeline is correct on real data. It does **not**
validate mid-lap delta *magnitudes* in slow corners, which carry roughly
±0.1–0.2 s of alignment uncertainty (see below). The history of the
BLOCKED investigation that preceded this result is kept further down,
unchanged.

## Real pair results (fixture `scripts/fixtures/real-openf1-pair/`)

Session 9161, 2023 Singapore GP qualifying (Marina Bay). **Driver 55
(Sainz) lap 19, 90.984 s** — Sainz's recorded pole time, an independent
confirmation that the identity is genuine — against **driver 63 (Russell)
lap 16, 91.056 s**. Both sector sets sum exactly to their lap times.
Fetched 2026-09-24 18:42 UTC by `scripts/fetch_real_driver_pair.py`, with
lap length 4940 m (Wikipedia, 2023 Singapore GP). Every number below is
reproducible with `python ../scripts/audit_real_pair.py`.

| | Driver 55 | Driver 63 |
|---|---:|---:|
| samples | 341 | 340 |
| telemetry starts after lap start | 0.295 s | 0.314 s |
| telemetry ends before lap end | 0.209 s | 0.062 s |
| largest gap (threshold 2.0 s) | 0.920 s | 0.880 s |
| valid speed / all channels present | 100% / yes | 100% / yes |
| integrated distance | 4848.9 m (−1.84%) | 4856.4 m (−1.69%) |
| trace confidence | HIGH, complete | HIGH, complete |

**Distance shortfall.** About 0.7% is the unobserved lap edges (28–38 m at
~270 kph). The remaining ~1.1% is systematic: after accounting for the
edges, the two drivers agree within 0.04%. That is consistent with the
racing line being shorter than the centreline an official length is
measured on, but it cannot be proven without position data. The lap length
was **not** adjusted to make the finish check pass.

**Official sector lines as fixed physical anchors (independent of this
codebase):**

| | located (55 / 63) | official split Δ | engine Δ | error |
|---|---|---:|---:|---:|
| S1 | 1608.2 / 1603.9 m | −0.068 s | −0.098 s | −0.030 s |
| S2 | 3399.1 / 3397.0 m | +0.025 s | +0.018 s | −0.007 s |

Both drivers' independently integrated distances place the same physical
lines 2–4 m apart. The signs match official timing at both lines. The
mean error, −0.0185 s, matches the −0.019 s bias predicted *before*
running the check. That bias comes from the start-offset difference:
elapsed time is measured from each driver's first telemetry sample, not
from the official lap start.

## Precision limits found on real data (open issues)

1. **Slow-corner alignment sensitivity.** An A/B distance misalignment of
   1 m is worth 12–13 ms at ~300 kph, but 38–46 ms at 78–95 kph. The
   reported max gain (−0.258 s at x=0.40, 78 kph) and max loss (+0.135 s
   at x=0.614, 95 kph) both sit in slow corners, where the observed 2–4 m
   misalignment means ±0.1–0.2 s. **They are not reliable engineering
   findings.** Position-based alignment (OpenF1 `/location` x,y) is the
   fix. That belongs to Phase 10.3.
2. **Confidence does not express alignment precision.** Those points are
   labelled HIGH, because `Confidence` reflects telemetry integrity only.
   Per-point alignment uncertainty (≈ misalignment_m / speed) is needed.
3. **Start-offset bias** of about |offA − offB| (19 ms here, bounded by one
   sample interval, ~0.27 s) in every delta. Removing it needs
   lap-start anchoring, which must not become extrapolation.
4. **Segmentation over-fragments.** There are 173 segments, 146 shorter
   than 50 m, and 124 changing by less than 10 ms. The 0.001 s default
   was a resolution floor pending real data; it needs calibration (for
   example, minimum span or minimum change in the order of the alignment
   uncertainty above).
5. **Finish not comparable** against the cited length: both traces end
   at x≈0.98.

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

(At the time of the BLOCKED investigation - now obtained, see "Real pair results".) Prepared:

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

## 15. Tests

With the real fixture committed (fresh run): backend **436 passed, 5
skipped**. The gate's 9 tests now run for real. The 5 skips are 2
Gemini-key tests, 2 pre-existing fixture/setup skips, and the finish
plausibility check (both traces end before x=1.0). Ruff `app/` baseline
218, unchanged. Frontend build OK, 51/51, 0 ESLint errors.

Before the fixture existed: 427 passed, 14 skipped. Added this phase: 13
identity/selection/integrity tests, 7 script plumbing tests, 1 route
honesty test, and 2 Section 16 regression tests. Red-green verified: the
three route fixes, the b521a32 coverage fix, the float tolerance, and the
acquisition-key fix. The identity guard and lap-selection rule were
mutation-checked.

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

## First local run (Windows) — acquisition bug found and fixed

The first real run reached OpenF1 successfully (no 401): the session and
laps resolved, and driver 55's lap 19 was selected. The car_data query then
returned **empty**. Root cause, confirmed by running OpenF1's own parser
(`br-g/openf1` `query_api/query_params.py`) on the exact bytes httpx sends:
the server rebuilds each filter as `f"{key}={value}"`. So the script's key
`date>=` arrived as `date>==<ts>`, which parsed as `>=` with the string
value `"=<ts>"` and matched nothing. The key `date>` arrives as
`date>=<ts>`, a correctly typed **inclusive** filter. That is the convention
`OpenF1Client._bounds` already used.

The script now uses `date>`/`date<`, and an empty window reports the exact
query it sent. The plumbing test had asserted the broken keys (a stub can
only check what the author believes the server wants). It now encodes
OpenF1's real behaviour, and it was proven red before the fix and green
after.

## Reproducing the acquisition (run locally, outside a live F1 session)

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
