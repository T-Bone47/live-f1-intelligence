# Phase 12A Spatial Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build validated, versioned, fail-closed spatial evidence from a
session's own OpenF1 location feed: a track reference, the official timing
lines measured on it, a claim-scoped gate, the state of every car at any time
t, and three API routes, all proven on the 2026 Dutch GP recording.

**Architecture:** This is a new backend package, `app/spatial/`, fed by the
recording. The pipeline runs source → reference → timing lines → gate →
sample classification → state, then contract, store and API. It reuses the
Phase 10.3 `Centerline`/`project_positions` and the `lap_distance`
confidence helpers instead of adding a second engine. Caches live next to
the recording, keyed like `timeline_v1`. There is no frontend, no DB
migration and no live hub.

**Tech Stack:** Python 3.11, FastAPI, pydantic v2, zstandard, and stdlib
(`array`, `bisect`, `hashlib`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-26-phase-12a-spatial-foundation-design.md`

## Global Constraints

**Working rules**
- Run everything from `backend/` with `./.venv/Scripts/python.exe`. The
  test command is `./.venv/Scripts/python.exe -m pytest <files> -q`.
- No new dependencies. Changed files must be ruff-clean
  (`./.venv/Scripts/python.exe -m ruff check <files>`). Never touch
  pre-existing lint debt.
- TDD: every test is red first. Commit only when green. Commit messages
  start with `phase12:` and end with the
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line.
- Zero fabrication: missing data becomes `None` / `Confidence.NONE` / a
  status. Never extrapolate past a driver's last sample. Never claim a
  corner, DRS zone, racing line or pit-lane path.

**Constants**

| constant | value | status |
|---|---|---|
| `MAP_SECTOR_P95_M` | 20.0 | user policy, 2026-09-26 |
| `CORNER_P95_M` | 5.0 | user policy, 2026-09-26 |
| `MIN_CROSSINGS` | 60 | PROVISIONAL |
| `INDEPENDENCE_MAX_M` | 20.0 | |
| `PIT_WINDOW_MIN_SHARE` | 0.90 | |
| tolerance quantile | 0.999 | |
| pit-inside-tolerance ceiling | 0.001 | |
| trace window cap | 600 s | resource guard |

**Reuse, never copy**
- `app.analysis.track_geometry`: `Centerline`, `project_positions`,
  `BACKTRACK_TOL_FRACTION`, `MAX_RATE_FACTOR`.
- `app.analysis.lap_distance`: `MAX_GAP_S` (2.0), `confidence_rank`.
- `app.analysis.common.models.Confidence`.
- `app.analysis.timeline.to_canonical_json`.
- `app.storage.timeline_store`: `index_recordings`,
  `recording_session_id`.

**Versions**
- `SPATIAL_BUILDER_VERSION = "spatial-builder-1.0.0"`.
- Contracts: `track_reference_v1`, `spatial_state_v1`,
  `spatial_trace_v1`.
- Response header: `X-Spatial-Contract`.

**Time**
- Internally, times are UTC epoch float seconds.
- In contracts, times are ISO-8601 with an offset (`isoformat()` of an
  aware UTC datetime).

**Repository**
- `.gitattributes` gains `docs/spatial/*.json -text`.
- The legacy `/api/v1/sessions/{sid}/circuit` route is unchanged.

## Review Focus

1. **An `at` with a non-UTC offset.** `"…T14:00:15+02:00"` must give the
   same state as `"…T12:00:15Z"`, and a naive `at` returns 422. Test:
   Task 10.
2. **A retired car.** After its last sample the car is `NO_COVERAGE`. It
   must not stay `STALE`, and it must not be pinned to its garage position.
   Test: Task 7.
3. **A session with no eligible reference lap.** `/track` returns 200
   `UNVALIDATED` with `NO_ELIGIBLE_REFERENCE_LAP`, and `/spatial` returns
   409. Test: Tasks 8 and 10.
4. **A circuit absent from `circuits.json`.** Metres are null, both claims
   fail with `NO_CITED_LAP_LENGTH`, and the status is `UNVALIDATED`. Test:
   Tasks 5 and 8.
5. **Two concurrent first requests.** There must be exactly one build, and
   both callers get identical bytes. Test: Task 9.

---

### Task 1: Centerline distance → XY and closed loops

**Files:**
- Modify: `backend/app/analysis/track_geometry.py` (class `Centerline`)
- Test: `backend/tests/test_track_geometry.py` (append)

**Interfaces:**
- Produces:
  - `Centerline.is_closed: bool`, true when `points[0] == points[-1]`;
  - `Centerline.point_at(s: float) -> tuple[float, float]`. On a closed
    path `s` is taken modulo `total_length`; on an open path it is clamped
    to `[0, total_length]`.

- [ ] **Step 1: Write the failing tests**

```python
SQ = [(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0)]

def test_point_at_returns_vertices_and_interpolates_within_a_segment():
    c = Centerline(SQ + [SQ[0]])
    assert c.point_at(0) == (0.0, 0.0)
    assert c.point_at(400) == (400.0, 0.0)
    assert c.point_at(600) == (400.0, 200.0)

def test_point_at_wraps_on_a_closed_loop_and_clamps_on_an_open_path():
    closed, opened = Centerline(SQ + [SQ[0]]), Centerline(SQ[:3])
    assert closed.is_closed and not opened.is_closed
    assert closed.point_at(1650) == closed.point_at(50)
    assert closed.point_at(-50) == closed.point_at(1550)
    assert opened.point_at(-5) == (0.0, 0.0)
    assert opened.point_at(10_000) == (400.0, 400.0)

def test_point_at_round_trips_through_project():
    c = Centerline(SQ + [SQ[0]])
    for s in (0.0, 123.4, 399.999, 1234.5, 1599.0):
        assert abs(c.project(*c.point_at(s)).s - s) < 1e-9

def test_closing_the_loop_stops_points_before_the_line_clamping_to_zero():
    # the open-polyline clamp found by the 12A spike
    assert Centerline(SQ).project(0.0, 5.0).s == 0.0
    assert Centerline(SQ + [SQ[0]]).project(0.0, 5.0).s == 1595.0
```

- [ ] **Step 2: Run the tests; they must fail**
  - Run: `./.venv/Scripts/python.exe -m pytest tests/test_track_geometry.py -q`
  - Expected: FAIL (`AttributeError: 'Centerline' object has no attribute 'point_at'`).
- [ ] **Step 3: Implement `is_closed` and `point_at`** in `Centerline`.
  Find the segment by bisecting `self.cum`, then interpolate linearly.
- [ ] **Step 4: Run the file; every test must pass**, including the 16
  existing 10.3 tests.
- [ ] **Step 5: Commit** with the message `phase12: Centerline.point_at and closed-loop projection`.

---

### Task 2: Session spatial inputs from a recording

**Files:**
- Create: `backend/app/spatial/__init__.py` (package docstring only)
- Create: `backend/app/spatial/source.py`
- Modify: `backend/app/ingest/recorder.py` (add `iter_recording_models`)
- Modify: `.gitattributes` (add `docs/spatial/*.json -text`)
- Create: `backend/tests/spatial_synth.py` (synthetic session, used by
  every later task)
- Test: `backend/tests/test_spatial_source.py`

**Interfaces:**
- **Produces, in `recorder.py`:**
  - `iter_recording_models(frames_path: Path, include_types: frozenset[str], count_markers: Mapping[str, tuple[bytes, ...]] | None = None, counts: dict[str, int] | None = None) -> Iterator[tuple[dict, dict]]`
  - It yields `(envelope_without_payload, model)` for lines that contain
    `"type":"<T>"` for any T in `include_types`.
  - `count_markers` maps a name to byte patterns that must *all* be present
    in a line for that line to be counted into `counts[name]`, without
    parsing it.
- **Produces, in `source.py`:**

```python
MODEL_TYPES = frozenset({"SessionInfo", "Driver", "Lap", "PitStop", "TelemetryLocationSample"})
class SpatialIdentityError(ValueError): ...
Sample = tuple[float, float, float]                      # (t epoch s, x, y)
@dataclass(frozen=True)
class LapRow: driver: int; lap: int; start: float; duration: float | None; s1: float | None; s2: float | None; pit_out: bool
@dataclass(frozen=True)
class PitRow: driver: int; ts: float; lap: int | None; lane_s: float | None
@dataclass(frozen=True)
class SpatialInputs:
    session_id: str
    session: dict                                        # SessionInfo model without provenance
    drivers: tuple[int, ...]                             # sorted, from Driver envelopes
    laps: dict[int, tuple[LapRow, ...]]                  # by lap number
    pits: dict[int, tuple[PitRow, ...]]                  # by ts
    samples: dict[int, tuple[Sample, ...]]               # by t, keyed by the MODEL's driver_number
    counts: dict[str, int]  # null_xy, no_fix, duplicate_identical, duplicate_conflicting, car_samples, car_drs_null
    input_digest: str                                    # sha256 hex, canonical JSON of laps, pits and samples
def inputs_from_rows(session_id: str, rows: Iterable[tuple[dict, dict]], counts: Mapping[str, int] | None = None) -> SpatialInputs
def load_inputs(recording_dir: Path, session_id: str) -> SpatialInputs
```

**Rules**
- **Identity.** Each of these raises `SpatialIdentityError`, naming the
  type, the driver and the envelope `seq`:
  - the envelope's `session_id` differs from the requested session;
  - the model's `session_id` is present and differs;
  - the envelope's `driver_number` is non-null and differs from the model's
    `driver_number`.
- **Dropped samples:**
  - `x` or `y` is null → drop, count `null_xy`;
  - an exact `(0.0, 0.0, 0.0)` → drop, count `no_fix`;
  - the same (driver, t) with identical (x, y) → keep one, count the dropped
    copies in `duplicate_identical`;
  - the same (driver, t) with different (x, y) → drop all of them, count
    the dropped samples in `duplicate_conflicting`.
- **DRS counts.** `load_inputs` passes
  `count_markers={"car_samples": (b'"type":"TelemetryCarSample"',), "car_drs_null": (b'"type":"TelemetryCarSample"', b'"drs":null')}`.

**Synthetic session** (`tests/spatial_synth.py`, used by every later task):

```python
SID = "openf1:1"; T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SIDE = 1000.0; LENGTH = 4 * SIDE; FINISH_S = SIDE / 2; LAP_S = 60.0; DT = 0.25
def track_xy(s: float) -> tuple[float, float]: ...     # CCW square from (0,0) along +x; s mod LENGTH
@dataclass(frozen=True)
class Car: number: int; start_offset_s: float = 0.0; lap_s: float = LAP_S; sample_phase_s: float = 0.0; last_sample_s: float | None = None
@dataclass(frozen=True)
class Pit: driver: int; lap: int; exit_at_s: float; lane_s: float = 20.0
def synth_rows(cars=(Car(1), Car(2, 2.0, sample_phase_s=0.1), Car(3, 4.0, sample_phase_s=0.2)),
               laps: int = 6, pits: tuple[Pit, ...] = (), circuit: str = "Synthetic",
               extra: tuple[tuple[dict, dict], ...] = ()) -> list[tuple[dict, dict]]
def location_row(driver: int, t: datetime, x: float | None, y: float | None, z: float | None = 1.0) -> tuple[dict, dict]
def write_recording(root: Path, rows: list[tuple[dict, dict]], sid: str = SID, name: str = "openf1-1-race") -> Path
```

**Synthetic kinematics**
- A car crosses `FINISH_S` at `T0 + start_offset + k·lap_s`, and
  `s(t) = FINISH_S + (t − T0 − start_offset)·LENGTH/lap_s`.
- Samples fall every `DT` from `T0 + start_offset − 5 + sample_phase` to
  5 s after the last lap (or to `last_sample_s`).
- Lap `k+1` has `started_at` = crossing `k`, `duration = lap_s`, and
  `sector1 = sector2 = lap_s/3`.
- **Pit** (EXIT semantics, as the real data suggests): during
  `[exit − lane, exit]` the car's samples are displaced to `(x, y − 200)`,
  and a `PitStop` row has `ts = exit`, `lap_number = lap` and
  `lane_duration_s = lane`.
- **Recording:** `write_recording` wraps the rows as `Envelope`s (the same
  shape as `tests/test_session_timeline.env`) and writes them through
  `app.ingest.recorder.Recorder`.

- [ ] **Step 1: Write the failing tests** in `test_spatial_source.py`:
  - `test_rows_are_bucketed_by_their_own_driver_and_time_sorted`: rows in
    shuffled order give `samples[d]` strictly increasing in t, and every
    sample of car d lies on car d's synthetic path.
  - `test_a_row_from_another_session_fails_closed`: one Lap with
    `session_id="openf1:2"` → `pytest.raises(SpatialIdentityError)`.
  - `test_an_envelope_driver_that_disagrees_with_its_model_fails_closed`.
  - `test_null_and_zero_triple_positions_are_dropped_and_counted`:
    `counts["null_xy"] == 1` and `counts["no_fix"] == 1`, and neither row is
    in `samples`.
  - `test_identical_duplicates_keep_one_and_conflicting_duplicates_drop_all`:
    `duplicate_identical == 1`, `duplicate_conflicting == 2`, and neither
    conflicting t remains.
  - `test_load_inputs_reads_a_recording_and_counts_drs_nulls`: three extra
    `TelemetryCarSample` rows (two with `drs` null) give `car_samples == 3`
    and `car_drs_null == 2`. `input_digest` must equal the one from
    `inputs_from_rows`.
  - `test_input_digest_changes_when_any_sample_changes`.
- [ ] **Step 2: Run the file; the tests must fail** (import errors).
- [ ] **Step 3: Implement** `iter_recording_models`, `inputs_from_rows`
  and `load_inputs`.
  - Parse `datetime.fromisoformat(...).timestamp()`.
  - Compute the digest as
    `sha256(json.dumps({"laps": [...], "pits": [...], "samples": {str(d): [...]}}, sort_keys=True, separators=(",", ":")))`
    over sorted tuples.
- [ ] **Step 4: Run the file; every test must pass**, then run ruff on the
  changed files.
- [ ] **Step 5: Commit** with the message `phase12: spatial inputs from a recording, identity-guarded`.

---

### Task 3: Deterministic reference lap

**Files:**
- Create: `backend/app/spatial/reference.py`
- Test: `backend/tests/test_spatial_reference.py`

**Interfaces:**
- Consumes: `SpatialInputs`, `LapRow` (Task 2) and `Centerline` (Task 1).
- Produces:

```python
class NoReferenceLap(ValueError): ...
def pit_adjacent(inputs: SpatialInputs) -> frozenset[tuple[int, int]]   # (driver, pit.lap) and (driver, pit.lap + 1)
def eligible_laps(inputs: SpatialInputs, *, require_coverage: bool) -> list[LapRow]
def reference_candidates(inputs: SpatialInputs, k: int = 3) -> list[LapRow]  # eligible with coverage, sorted by (duration, driver, lap)
@dataclass(frozen=True)
class Reference: driver: int; lap: int; start: float; duration: float; points: tuple[tuple[float, float], ...]; centerline: Centerline
def build_reference(inputs: SpatialInputs, lap: LapRow) -> Reference   # closed: points[0] == points[-1]
```

**Eligibility and coverage**
- A lap is eligible when it is timed (`duration` present), has
  `lap ≥ 2`, is not `pit_out`, and is not in `pit_adjacent`.
- Coverage means, for the driver's samples inside
  `[start, start + duration]`:
  - the first is at or before `start + MAX_GAP_S`;
  - the last is at or after `start + duration − MAX_GAP_S`;
  - every consecutive gap is at most `MAX_GAP_S`.
- `build_reference` takes the consecutive distinct points, then appends the
  first. Fewer than 3 distinct points raises `NoReferenceLap`.

- [ ] **Step 1: Write the failing tests:**
  - `test_lap_1_pit_out_and_pit_adjacent_laps_are_never_eligible`:
    `Pit(2, 3, …)` excludes (2, 3) and (2, 4); lap 1 and a `pit_out` lap
    are also excluded.
  - `test_a_lap_with_a_location_gap_is_not_a_reference_candidate`: removing
    3 s of car 1 lap 2 takes it out of the candidates, but it stays in
    `eligible_laps(require_coverage=False)`.
  - `test_fastest_eligible_lap_wins_and_ties_break_by_driver_then_lap`:
    with equal laps the first candidate is `(1, 2)`; with
    `Car(3, 4.0, lap_s=59.0)` it is `(3, 2)`.
  - `test_reference_is_closed_and_lies_on_the_track`:
    `points[0] == points[-1]`, every point is within 1e-9 of the square, and
    `0 < LENGTH − centerline.total_length ≤ 40`. The 40 comes from corner
    chords: sample spacing is 16.7, and a chord cuts at most
    16.7·(2 − √2) ≈ 9.8 per corner.
  - `test_no_eligible_lap_raises_no_reference_lap` (`laps=1`).
- [ ] **Step 2: Run them; they must fail.**
- [ ] **Step 3: Implement** the functions above.
- [ ] **Step 4: Run them; they must pass.** Run ruff.
- [ ] **Step 5: Commit** with the message `phase12: deterministic reference lap`.

---

### Task 4: Timing lines measured from official timestamps

**Files:**
- Create: `backend/app/spatial/timing_lines.py`
- Test: `backend/tests/test_spatial_timing_lines.py`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces:

```python
LINES = ("FINISH", "S1", "S2")
def nearest_rank(values: Sequence[float], q: float) -> float        # sorted(values)[ceil(q*n) - 1]; ValueError if empty
def circular_median(fractions: Sequence[float]) -> float            # result in [0, 1)
def circular_diff(a: float, b: float) -> float                      # ((a - b + 0.5) % 1) - 0.5
def position_at(samples: Sequence[Sample], t: float, max_gap_s: float = MAX_GAP_S) -> tuple[float, float] | None
@dataclass(frozen=True)
class LineMeasurement:
    line: str; fraction: float; x: float; y: float; n: int; exclusions: dict[str, int]
    dispersion_fraction: dict[str, float]                           # median, p90, p95, p99, max
    dispersion_m: dict[str, float] | None                           # same keys; None without a cited length
    worst: tuple[tuple[int, int, float], ...]                       # top 5 (driver, lap, metres or fraction)
def measure_lines(inputs: SpatialInputs, ref: Reference, lap_length_m: float | None) -> dict[str, LineMeasurement]
def inter_line_fractions(lines: Mapping[str, LineMeasurement]) -> tuple[float, float, float]  # FINISH→S1, S1→S2, S2→FINISH, mod 1
def reference_independence_m(inputs: SpatialInputs, refs: Sequence[Reference], lap_length_m: float | None) -> float | None
```

**Algorithms**
- **Circular median:** sort; find the largest gap between consecutive
  values, including the wrap gap `1 − last + first`. Rotate so the values
  start just after that gap, take the ordinary median (the mean of the
  middle two when n is even), rotate back, and reduce mod 1.
- **Laps measured:** `eligible_laps(require_coverage=False)`, plus
  exclusion counts for every other lap row by reason: `LAP_1`,
  `PIT_ADJACENT` (which includes `pit_out`) and `UNTIMED`.
- **Probes:**
  - `FINISH` at `start`;
  - `S1` at `start + s1`;
  - `S2` at `start + s1 + s2`.
  - Probes missing a sector time count as `NO_SECTOR_TIME`.
  - `position_at` returning None counts as `NO_BRACKET` if t is outside
    the samples, else `GAP`.
- **Dispersion:** `|circular_diff(crossing, line)|`; metres are that ×
  `lap_length_m`.
- **Line position:** `(x, y) = ref.centerline.point_at(fraction × total_length)`.
- **Reference independence:** the maximum over the three inter-line
  distances of (max − min across the references) × `lap_length_m`. It is
  None without a length or with fewer than 2 references.

- [ ] **Step 1: Write the failing tests:**
  - `test_nearest_rank_and_circular_median`:
    - `nearest_rank(range(1, 11), .95) == 10` and
      `nearest_rank(range(1, 11), .9) == 9`;
    - `abs(circular_diff(circular_median([.98, .99, .01, .02]), 0.0)) < 1e-12`;
    - `circular_median([.2, .4, .3]) == .3`.
  - `test_position_at_interpolates_within_a_bracket_and_refuses_gaps`.
  - `test_lines_on_exact_geometry_have_zero_dispersion_and_known_spacing`,
    with `lap_length_m=4000.0`:
    - every `dispersion_m["max"] < 1e-6`;
    - `inter_line_fractions` equals `(1/3, 1/3, 1/3)` within 1e-9;
    - FINISH `(x, y)` is within 1e-6 of `track_xy(FINISH_S)`.
  - `test_exclusions_are_counted_by_reason`: a pit, lap 1, a lap with a
    null sector 1 (counted for S1 and S2 only) and a sample gap around a
    probe (counted as GAP).
  - `test_a_displaced_crossing_is_kept_and_listed_as_worst`: moving car 2's
    lap-4 start by +0.6 s gives
    `worst[0][:2] == (2, 4)` and `abs(worst[0][2] − 40.0) < 1e-6` on all
    three lines, with `n` unchanged (nothing trimmed).
  - `test_dispersion_metres_need_a_cited_length`: `lap_length_m=None` gives
    `dispersion_m is None`, and `dispersion_fraction` is still present.
  - `test_reference_independence_is_zero_on_exact_geometry`: the result is
    `< 1e-6`.
- [ ] **Step 2: Run them; they must fail.**
- [ ] **Step 3: Implement** the module.
- [ ] **Step 4: Run them; they must pass.** Run ruff.
- [ ] **Step 5: Commit** with the message `phase12: timing lines measured from official timestamps`.

---

### Task 5: Cited lap lengths and the claim-scoped gate

**Files:**
- Create: `backend/app/spatial/circuits.json`
- Create: `backend/app/spatial/circuits.py`
- Create: `backend/app/spatial/gate.py`
- Test: `backend/tests/test_spatial_gate.py`

**Interfaces:**
- Consumes: `LineMeasurement` (Task 4).
- Produces:

```python
CIRCUITS_PATH: Path                                               # module constant, patched by tests
@dataclass(frozen=True)
class CitedLength: lap_length_m: float; source: str
def load_circuits(path: Path | None = None) -> dict[str, CitedLength]   # key = circuit_short_name exactly as stored
def cited_lap_length(circuit_short_name: str | None, circuits: Mapping[str, CitedLength] | None = None) -> CitedLength | None
MAP_SECTOR_P95_M = 20.0; CORNER_P95_M = 5.0; MIN_CROSSINGS = 60; INDEPENDENCE_MAX_M = 20.0
@dataclass(frozen=True)
class GateResult: claim: str; passed: bool; threshold_m: float; observed_p95_m: dict[str, float | None]; reasons: tuple[str, ...]
def evaluate_gate(lines: Mapping[str, LineMeasurement] | None, independence_m: float | None,
                  cited: CitedLength | None) -> dict[str, GateResult]   # keys "MAP_SECTOR", "CORNER"
```

**Reason codes:**
- `NO_CITED_LAP_LENGTH`;
- `NO_REFERENCE` (when `lines` is None);
- `TOO_FEW_CROSSINGS:<LINE>` (n < 60);
- `P95_ABOVE_THRESHOLD:<LINE>` (p95 > threshold, so exactly 20.0 passes);
- MAP_SECTOR only: `INDEPENDENCE_UNMEASURED` and
  `REFERENCE_DEPENDENT` (> 20.0).

CORNER uses the same n rule and a 5.0 threshold, with no independence
term, per spec §5.4.

- [ ] **Step 1: Verify the citation before writing it.**
  - Fetch a primary page stating the Circuit Zandvoort lap length (the
    Formula 1 Dutch GP circuit page or Wikipedia "Circuit Zandvoort") with
    WebFetch.
  - Write `{"Zandvoort": {"lap_length_m": 4259.0, "source": "<page title>, <URL>, accessed 2026-09-26"}}`
    only if the page states 4.259 km.
  - If it cannot be verified, leave the file as `{}`. Task 11 then reports
    UNVALIDATED honestly.
  - The key `Zandvoort` is the stored `circuit_short_name` (verified in the
    recording's `meta.json`).
- [ ] **Step 2: Write the failing tests:**
  - `test_zandvoort_is_cited_and_unknown_circuits_are_not`:
    `lap_length_m == 4259.0` and `"http" in source`; `"Nowhere"` and
    `None` both give `None`.
  - `test_map_sector_passes_at_exactly_20_m_and_fails_just_above`: an S2
    p95 of 20.0 passes; 20.000001 fails with `P95_ABOVE_THRESHOLD:S2`.
  - `test_corner_threshold_is_5_m`.
  - `test_crossings_boundary_59_fails_60_passes`.
  - `test_no_cited_length_fails_both_claims` (Review Focus 4).
  - `test_unmeasured_or_reference_dependent_fails_map_sector_only`.
- [ ] **Step 3: Run them; they must fail.** Then implement.
- [ ] **Step 4: Run them; they must pass.** Run ruff.
- [ ] **Step 5: Commit** with the message `phase12: cited lap lengths and the claim-scoped gate`.

---

### Task 6: Classify every location sample

**Files:**
- Create: `backend/app/spatial/samples.py`
- Test: `backend/tests/test_spatial_samples.py`

**Interfaces:**
- Consumes: Tasks 2-4, plus `project_positions` and `TelemetryLocationSample`
  (built with `model_construct`, so no validation runs; identity was
  already guarded in Task 2).
- Produces:

```python
class SampleFlag(str, Enum): ON_REFERENCE = "ON_REFERENCE"; PIT_LANE = "PIT_LANE"; OFF_REFERENCE = "OFF_REFERENCE"
PIT_WINDOW_MIN_SHARE = 0.90; TOL_QUANTILE = 0.999; PIT_INSIDE_MAX_SHARE = 0.001
def lateral_offsets(inputs: SpatialInputs, ref: Reference, laps: Sequence[LapRow]) -> list[float]   # feed units
def derive_tolerance(inputs: SpatialInputs, ref: Reference, green: Sequence[LapRow]) -> tuple[float, dict[str, float], int]
    # (tol, {"p50","p90","p99","p999"}, n)
def pit_windows(inputs: SpatialInputs, mode: Literal["ENTRY", "EXIT"]) -> list[tuple[int, float, float]]  # rows without lane_s skipped
@dataclass(frozen=True)
class PitWindowResult: mode: Literal["ENTRY", "EXIT", "NONE"]; share_entry: float | None; share_exit: float | None; samples_entry: int; samples_exit: int
def choose_pit_mode(inputs: SpatialInputs, ref: Reference, tol: float) -> PitWindowResult
def inside_share(inputs: SpatialInputs, ref: Reference, tol: float, windows: Sequence[tuple[int, float, float]]) -> tuple[float | None, int]
@dataclass(frozen=True)
class ClassifiedSample: t: float; x: float; y: float; flag: SampleFlag; fraction: float | None; lap: int | None; confidence: Confidence
def classify_driver(inputs: SpatialInputs, driver: int, ref: Reference, finish_fraction: float, tol: float,
                    windows: Sequence[tuple[int, float, float]]) -> list[ClassifiedSample]
```

**Classification rules** (spec §5.5)
- Inside one of the driver's windows → `PIT_LANE`, with no fraction and no
  lap.
- Otherwise, a windowed-projection offset > `tol` → `OFF_REFERENCE`.
- Otherwise the sample is `ON_REFERENCE`:
  - If it lies inside a timed lap window (the lap with the greatest
    `start ≤ t` and `t ≤ start + duration`), `project_positions` runs over
    that lap's on-reference samples. Its `ProjectedPosition.confidence`
    becomes the sample's confidence. NONE means the fraction is withheld.
    The fraction is `(unwrapped − finish_fraction) % 1`, and lap is the lap
    number.
  - Otherwise, fraction comes from the raw projection, lap is None and
    confidence is LOW.
- `PIT_LANE` and `OFF_REFERENCE` samples keep their observed x/y at
  confidence HIGH.
- **Pit mode:** use the mode with the higher share if it is at least 0.90,
  else `NONE` (no windows used).

- [ ] **Step 1: Write the failing tests:**
  - `test_tolerance_is_the_p999_of_green_lap_offsets`: equals
    `nearest_rank(lateral_offsets(...), 0.999)` and is below 10 (synthetic
    corner-chord error).
  - `test_exit_pit_mode_is_detected_when_the_window_ends_at_ts`:
    `Pit(2, 3, …)` gives mode `EXIT`, with `share_exit ≥ 0.9 > share_entry`.
  - `test_pit_mode_is_none_when_neither_window_is_off_reference`: an extra
    `PitStop` row with no displacement.
  - `test_pit_lane_samples_keep_xy_but_get_no_fraction`.
  - `test_off_reference_garage_samples_get_no_fraction`: extra rows 500
    units off the track mid-race.
  - `test_on_reference_fraction_is_measured_from_the_finish_line`: car 1 at
    `crossing₁ + 15 s` has fraction `0.25 ± 1e-9` and lap `2`.
  - `test_samples_outside_timed_laps_are_low_confidence_without_a_lap`: the
    5 s before the first crossing.
  - `test_a_backward_jump_is_withheld_not_repaired`: one sample moved 100
    units backwards mid-lap gets fraction None and confidence NONE.
- [ ] **Step 2: Run them; they must fail.** Then implement.
- [ ] **Step 3: Run them; they must pass.** Run ruff.
- [ ] **Step 4: Commit** with the message `phase12: classify every location sample`.

---

### Task 7: Spatial state at time t and driver traces

**Files:**
- Create: `backend/app/spatial/state.py`
- Test: `backend/tests/test_spatial_state.py`

**Interfaces:**
- Consumes: `ClassifiedSample` and `SampleFlag` (Task 6), `Centerline`
  (Task 1).
- Produces:

```python
FLAG_CODES = {SampleFlag.ON_REFERENCE: 0, SampleFlag.PIT_LANE: 1, SampleFlag.OFF_REFERENCE: 2}
CONF_CODES = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1, Confidence.NONE: 0}
@dataclass
class DriverTrack:            # parallel arrays, time-sorted
    t: array; x: array; y: array; fraction: array   # 'd'; fraction NaN = None
    flag: array; confidence: array                  # 'b'
    lap: array                                      # 'h'; -1 = None
def track_from_samples(samples: Sequence[ClassifiedSample]) -> DriverTrack
@dataclass
class SpatialIndex:
    session_id: str; track_id: str; ref_points: tuple[tuple[float, float], ...]; finish_fraction: float
    lap_length_m: float | None; tracks: dict[int, DriverTrack]
    centerline: Centerline      # built from ref_points in __post_init__
def state_at(index: SpatialIndex, t: float) -> list[dict]      # sorted by driver; keys = spatial_state_v1 driver fields
def trace(index: SpatialIndex, driver: int, t0: float, t1: float) -> list[dict]
```

**State rules** (spec §5.6)
- **Bracket.** `before` is the last sample with `t_i ≤ t`; `after` is the
  first with `t_i ≥ t`. At a sample's own time, both are that sample.
- **Outside coverage.** Before the first or after the last sample, the
  status is `NO_COVERAGE` and every field is None.
- **STALE.** A gap over `MAX_GAP_S` gives `STALE`, carrying the before
  sample's values at confidence LOW with `age_s = t − t_before`. It is
  never interpolated.
- **POSITIONED with a fraction.** Both samples must be `ON_REFERENCE` with
  fractions, and their laps must be equal, consecutive, or both None.
  - Unwrap: if `fb < fa − 0.5`, add 1 to `fb`, then interpolate.
  - `lap = lap_a if f < 1 else lap_b`, then `f %= 1`.
  - `(x, y) = centerline.point_at(((f + finish_fraction) % 1) × total_length)`.
  - `distance_m = f × lap_length_m` (None without a length).
  - Confidence is the worse of the two, by `confidence_rank`.
- **POSITIONED without a fraction.** Otherwise the fraction is None and x/y
  are linear. The flag is the worse one (`PIT_LANE` > `OFF_REFERENCE` >
  `ON_REFERENCE`), and confidence is the worse of the two.
- **Driver entry keys:** `driver_number`, `status`, `flag`, `confidence`,
  `x`, `y`, `reference_fraction`, `distance_m`, `lap_number`, `bracket`
  (`{before, after, gap_s}` as ISO strings and seconds, or None), `age_s`.

- [ ] **Step 1: Write the failing tests:**
  - `test_state_at_a_sample_time_equals_that_sample`: over 200
    seeded-random sample times, x, y and fraction match exactly.
  - `test_between_samples_the_fraction_is_interpolated_on_the_reference`:
    car 1 at `crossing₁ + 15.1 s` has fraction `15.1/60 ± 1e-9`, and x/y
    within 1e-6 of `track_xy(FINISH_S + 15.1·LENGTH/60)`.
  - `test_interpolation_unwraps_across_the_finish_line`: at
    `crossing₂ + 0.1 s` the fraction is `0.1/60 ± 1e-9` and the lap is 3.
  - `test_gap_over_2_s_is_stale_with_age_and_never_interpolated`.
  - `test_a_retired_car_has_no_coverage_after_its_last_sample` (Review
    Focus 2): `Car(3, 4.0, last_sample_s=130.0)` is `NO_COVERAGE` at
    `T0 + 200 s`.
  - `test_other_drivers_rows_never_change_a_drivers_state`: indexes built
    with and without car 2 give identical car-1 states at 100 times.
  - `test_trace_returns_the_raw_classified_samples_in_order`.
  - `test_pit_lane_state_has_xy_but_no_fraction`.
- [ ] **Step 2: Run them; they must fail.** Then implement.
- [ ] **Step 3: Run them; they must pass.** Run ruff.
- [ ] **Step 4: Commit** with the message `phase12: spatial state at time t and driver traces`.

---

### Task 8: Contracts and the builder

**Files:**
- Create: `backend/app/spatial/contract.py`
- Create: `backend/app/spatial/builder.py`
- Test: `backend/tests/test_spatial_contract.py`

**Interfaces:**
- Consumes: Tasks 2-7.
- Produces:

```python
SPATIAL_BUILDER_VERSION = "spatial-builder-1.0.0"
TRACK_CONTRACT = "track_reference_v1"; STATE_CONTRACT = "spatial_state_v1"; TRACE_CONTRACT = "spatial_trace_v1"
class SpatialContractError(ValueError): ...
def make_track_id(session_id: str, input_digest: str, cited: CitedLength | None) -> str
    # "trk1_" + sha256(json [SPATIAL_BUILDER_VERSION, session_id, input_digest, length|null, source|null])[:24]
def validate_track(doc: dict) -> None; def validate_state(doc: dict) -> None; def validate_trace(doc: dict) -> None
def build_spatial(inputs: SpatialInputs, circuits: Mapping[str, CitedLength] | None = None) -> tuple[dict, SpatialIndex | None]
def state_doc(index: SpatialIndex, at: datetime) -> dict
def trace_doc(index: SpatialIndex, driver: int, t0: datetime, t1: datetime) -> dict
```

**`track_reference_v1` top-level fields** (spec §6)
- `contract_version`, `builder_version`, `track_id`, `status`.
- `session`: `session_id`, `circuit_short_name`, `session_type`, `year`,
  `date_start`.
- `circuit`: `short_name`, `lap_length_m`, `lap_length_source`, with
  nulls when uncited.
- `coordinate_system`: `kind`, `units`, `origin`,
  `measured_units_per_metre` (null when uncited).
- `reference`: `driver_number`, `lap_number`, `started_at`, `duration_s`,
  `point_count`, `loop_length_feed_units`, `polyline` (null unless
  validated). The whole object is null without a reference.
- `timing_lines[]`: `line`, `fraction`, `distance_m`, `x`, `y`, `n`,
  `exclusions`, `dispersion_m`, `dispersion_fraction`, `worst[]`.
- `validation`:
  - `gates{MAP_SECTOR, CORNER}`;
  - `reference_independence_m`;
  - `on_reference_tol{feed_units, n, lateral_percentiles, pit_inside_share, provisional}`;
  - `pit_windows{mode, share_entry, share_exit, samples_entry, samples_exit}`;
  - `reasons[]`.
- `capabilities`: `racing_line{available: false, lateral_percentiles}`,
  `drs_zones{available: false, car_samples, drs_null}`,
  `corners{available: false, reason}`,
  `pit_lane_geometry{available: false, reason}`.
- `limitations[{code, message}]`, using the spec §7 codes.
- `provenance`: `chain[]`, `input_digest`, `counts`,
  `reference_candidates[]`.
- The state and trace docs carry `lap_length_m`, so metres can be
  validated.

**Builder flow**
1. Take `reference_candidates(k=3)`. If there are none: `UNVALIDATED`,
   reason `NO_ELIGIBLE_REFERENCE_LAP`, empty lines, null reference, no
   index.
2. Otherwise build the reference from candidate 0.
3. Measure the lines, the independence over all candidates, and the gates.
4. Derive the tolerance from `eligible_laps(require_coverage=False)`.
5. Choose the pit mode, and take `inside_share` over its windows (or over
   both hypotheses' windows when the mode is NONE).
6. Classify every driver.
7. Set the status to `VALIDATED_MAP_SECTOR` only if MAP_SECTOR passed; only
   then build the index and publish the polyline.
8. `measured_units_per_metre` = `loop_length / cited length`.
9. Add `CORNER_PRECISION_NOT_MET` only when CORNER failed.
   `RECORDING_ONLY` and `FEED_LINE_NOT_RACING_LINE` are always present, and
   `INTERPOLATED_BETWEEN_SAMPLES` goes on state and trace docs.

**Validators** (pydantic: `extra="forbid"`, `strict=True`,
`allow_inf_nan=False`, plus cross-field checks) reject:
- `VALIDATED` without a polyline or without MAP_SECTOR passed;
- `UNVALIDATED` with a polyline;
- a `track_id` that differs from the one recomputed from `session`,
  `provenance.input_digest` and `circuit`;
- `POSITIONED` without a bracket, and `STALE` without `age_s`;
- `NO_COVERAGE` with any value;
- a fraction on a non-`ON_REFERENCE` flag;
- `distance_m` without a fraction or without `lap_length_m`;
- unsorted or duplicate drivers.

- [ ] **Step 1: Write the failing tests:**
  - `test_synthetic_track_doc_validates_and_is_deterministic`: two builds
    give identical `to_canonical_json` bytes.
  - `test_track_id_changes_with_data_version_and_citation`.
  - `test_unvalidated_session_has_no_polyline_and_no_index` (Review Focus
    4): the circuit is uncited, and the reasons include
    `NO_CITED_LAP_LENGTH`.
  - `test_no_eligible_reference_lap_is_unvalidated` (Review Focus 3).
  - `test_capabilities_state_no_corners_no_drs_no_racing_line_with_evidence`.
  - `test_tampered_documents_are_rejected`, parametrized over 10 cases:
    - an extra `cause` field; NaN in `dispersion_m`;
    - a fraction on a `PIT_LANE` driver; `distance_m` with a null
      `lap_length_m`;
    - `POSITIONED` without a bracket; `STALE` without `age_s`;
    - a polyline on `UNVALIDATED`; a tampered `track_id`;
    - an unknown status; a duplicate driver.

    Each must raise `SpatialContractError`.
- [ ] **Step 2: Run them; they must fail.** Then implement.
- [ ] **Step 3: Run them; they must pass.** Run ruff.
- [ ] **Step 4: Commit** with the message `phase12: spatial contracts and builder`.

---

### Task 9: Spatial store, cached next to the recording

**Files:**
- Create: `backend/app/storage/spatial_store.py`
- Test: `backend/tests/test_spatial_store.py`

**Interfaces:**
- Consumes: `load_inputs` (Task 2), `build_spatial` and the validators
  (Task 8), `SpatialIndex` (Task 7), `index_recordings`.
- Produces:

```python
TRACK_CACHE = "track_reference_v1.json"; INDEX_CACHE = "spatial_samples_v1.bin"; KEY_SUFFIX = ".key"
class SpatialStore:
    def __init__(self, recordings_dir: Path, circuits: Mapping[str, CitedLength] | None = None) -> None
    def get_track(self, session_id: str) -> dict | None          # None = no recording
    def get_track_bytes(self, session_id: str) -> bytes | None
    def get_index(self, session_id: str) -> SpatialIndex | None  # None = no recording or UNVALIDATED
def write_index(path: Path, index: SpatialIndex) -> None
def read_index(path: Path) -> SpatialIndex
```

**Cache format and rules**
- **Header.** The index file starts with one JSON line:
  `{"format":"spatial-samples-v1","byteorder":sys.byteorder,"session_id","track_id","finish_fraction","lap_length_m","ref_points","drivers":[{"driver","n"}]}`.
  Then come each driver's arrays in the order t, x, y, fraction, flag,
  confidence, lap.
- **Byte order.** A mismatched `byteorder` means rebuild.
- **Keys.** Both caches use the key
  `f"{SPATIAL_BUILDER_VERSION}|{frames size}|{frames mtime_ns}"`.
- **Rebuild, never serve.** A missing, stale, unreadable or short cache is
  rebuilt and overwritten.
- **Lock.** One lock per store, with an in-memory cache inside it.
- **Identity.** The track's `session.session_id`, the index header's
  `session_id` and the `track_id` must all match. Otherwise
  `SpatialIdentityError`.

- [ ] **Step 1: Write the failing tests.** They use `write_recording` and
  `circuits={"Synthetic": CitedLength(4000.0, "synthetic test geometry")}`.
  - `test_first_request_builds_both_caches_then_serves_from_disk`: a second
    store instance, with `build_spatial` monkeypatched to raise, still
    serves.
  - `test_a_stale_key_rebuilds`: both a changed frames mtime and a
    monkeypatched builder version trigger a rebuild.
  - `test_a_corrupted_cache_is_rebuilt_not_served`: both a truncated `.bin`
    and invalid JSON.
  - `test_index_round_trips_exactly`: equal arrays, and `state_at` equal at
    50 times.
  - `test_a_recording_of_another_session_fails_closed`.
  - `test_concurrent_first_requests_build_once` (Review Focus 5): four
    threads give one `build_spatial` call and identical bytes.
  - `test_unvalidated_track_has_no_index`.
- [ ] **Step 2: Run them; they must fail.** Then implement.
- [ ] **Step 3: Run them; they must pass.** Run ruff.
- [ ] **Step 4: Commit** with the message `phase12: spatial cache next to the recording`.

---

### Task 10: API routes

**Files:**
- Modify: `backend/app/api/__init__.py`. Add three routes after
  `/timeline`, and a helper `_spatial_store(recordings_dir)` that mirrors
  `_timeline_store`.
- Test: `backend/tests/test_spatial_api.py`

**Interfaces:**
- Consumes: `SpatialStore`, `state_doc`, `trace_doc`, the validators and
  `to_canonical_json`.
- Produces:
  - `GET /api/v1/sessions/{session_id}/track`
  - `GET /api/v1/sessions/{session_id}/spatial?at=`
  - `GET /api/v1/sessions/{session_id}/spatial/{driver_number:int}?from=&to=`
  - All use `rate_limit_dependency` and `validate_session_id`. Store work
    runs in `asyncio.to_thread`. Every 200 carries `X-Spatial-Contract`.

**Error bodies:**
- a naive `at`, `from` or `to` → 422 `"<param> must carry a UTC offset"`.
  An offset is converted to UTC;
- `from ≥ to` → 422;
- `to − from > 600 s` → 422;
- a driver outside 1-99 → 422;
- a driver not in the index → 404;
- no recording → 404 `"no recording for {sid}: spatial data unavailable (built from recordings only)"`;
- UNVALIDATED → 409 with a JSON detail
  `{"message": "spatial geometry not validated for this session", "status": "UNVALIDATED", "reasons": [...]}`;
- `SpatialContractError` or `SpatialIdentityError` → 500
  `"spatial output withheld (fail closed): …"`.

- [ ] **Step 1: Write the failing tests.** They use `app_factory` as in
  `test_timeline_api.py`, and monkeypatch
  `app.spatial.circuits.CIRCUITS_PATH` to a tmp JSON holding
  `"Synthetic"`.
  - `test_track_route_serves_the_builder_bytes`: the bytes equal
    `to_canonical_json(build_spatial(...)[0])` and the header is present.
  - `test_state_route_positions_every_car_mid_race`.
  - `test_at_with_an_offset_is_converted_to_utc_and_naive_at_is_422`
    (Review Focus 1).
  - `test_trace_route_limits_and_errors`: from ≥ to gives 422; 601 s gives
    422; driver 0 gives 422; driver 42 gives 404.
  - `test_unvalidated_geometry_is_409_with_reasons`: with no circuits
    override, the session is uncited.
  - `test_session_without_reference_lap_is_409` (Review Focus 3).
  - `test_no_recording_is_404_for_all_three_routes`.
  - `test_repeated_requests_are_byte_identical`.
  - `test_legacy_circuit_route_is_unchanged`: it still returns 404 when no
    hub is running, exactly as before.
- [ ] **Step 2: Run them; they must fail.** Then implement.
- [ ] **Step 3: Run the new tests plus `tests/test_timeline_api.py` and
  `tests/test_discovery_api.py`; all must pass.** Run ruff on the changed
  files only.
- [ ] **Step 4: Commit** with the message `phase12: spatial routes (track, state at t, driver trace)`.

---

### Task 11: Dutch GP real-data validation and golden

**Files:**
- Create: `backend/tests/test_spatial_real.py`
- Create: `scripts/spatial_report.py`
- Create: `docs/spatial/track_reference_v1_dutch_gp_2026.json` (generated)
- Create: `docs/PHASE_12_SPATIAL_VALIDATION.md`

**Interfaces:**
- Consumes everything. The recording gate is the same as in
  `test_session_timeline_real.py`: `F1INTEL_TIMELINE_RECORDING`, or
  `recordings/**/openf1-11353-race` with `meta.json`.
- `scripts/spatial_report.py [--recording DIR] [--write-golden]`:
  - prints the validation summary and the open-item analyses;
  - writes the golden with `--write-golden`.

- [ ] **Step 1: Write the real tests**, each marked `needs_recording`.
  - `test_real_inputs`:
    - 22 drivers;
    - `car_samples == 900900` and `car_drs_null == car_samples`;
    - the kept location samples plus every drop count equal the raw
      `TelemetryLocationSample` line count, taken by a separate byte-search
      pass.
  - `test_real_gate_map_sector_passes_and_corner_fails`.
  - `test_real_line_dispersion_matches_independent_brute_force`: recompute
    every crossing with a brute-force nearest-segment search written in the
    test (no hint, no `Centerline.project`) and `nearest_rank`. Median,
    p90, p95, p99 and max must match per line within 1e-6 m.
  - `test_real_reference_independence_within_20_m`.
  - `test_real_capabilities_are_evidenced`: no racing line (lateral
    percentiles present), no DRS (counts), no corners, no pit-lane
    geometry.
  - `test_real_pit_mode_is_measured`: if the mode is not NONE, its share is
    at least 0.9. The observed mode is asserted only after Step 3 records
    it; no hypothesis is pre-assumed.
  - `test_real_state_at_every_lap_frame_puts_the_leader_on_the_finish_line`:
    for every `LAP k` frame of `docs/timeline/session_timeline_v1_dutch_gp_2026.json`,
    `state_at(frame.at)` validates. For at least 95% of frames, the P1
    driver's `|circular_diff(fraction, 0)| × 4259 ≤ FINISH p95`. This
    checks Phase 11 against 12A.
  - `test_real_output_matches_the_committed_golden`: the bytes match.
- [ ] **Step 2: Run the report** with
  `./.venv/Scripts/python.exe ../scripts/spatial_report.py --write-golden`.
  - It records the cold build time and the gate outcome.
  - It resolves spec §13 from the data:
    - which pit mode, with its shares;
    - the tolerance and its separation;
    - for each listed worst crossing: the bracket gap, the neighbouring
      samples' times and offsets, any nearby pit window, and the lap row;
    - when the no-fix `(0, 0, 0)` samples occur relative to the first lap
      start and the red flag.
- [ ] **Step 3: Pin the measured facts.** Tighten
  `test_real_pit_mode_is_measured` to the observed mode, and add the §13
  findings as assertions where they are facts, e.g.
  `no_fix` occurs only before the first lap start. Run the file; it must
  pass.
- [ ] **Step 4: Write `docs/PHASE_12_SPATIAL_VALIDATION.md`.** Include:
  - the geometry source, coordinate system and method;
  - the per-line table (n, exclusions, median/p90/p95/p99/max) and the
    gates;
  - reference independence;
  - the tolerance derivation and separation;
  - the pit-window verdict;
  - each outlier and its data-backed cause;
  - the no-fix timing;
  - the DRS and racing-line evidence;
  - reproduction commands.
- [ ] **Step 5: Commit** with the message `phase12: Dutch GP spatial validation and golden`.

---

### Task 12: Mutation sweep, performance, documentation

**Files:**
- Create: `scripts/bench_spatial.py`
- Create: `docs/PHASE_12_SPATIAL_INTELLIGENCE.md`
- Modify: `docs/PHASE_12_SPATIAL_VALIDATION.md` (add the mutation and
  performance tables)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Mutation sweep.** Apply each mutant alone. Run
  `./.venv/Scripts/python.exe -m pytest tests/test_spatial_source.py tests/test_spatial_reference.py tests/test_spatial_timing_lines.py tests/test_spatial_gate.py tests/test_spatial_samples.py tests/test_spatial_state.py tests/test_spatial_contract.py tests/test_spatial_store.py tests/test_spatial_api.py tests/test_track_geometry.py -q -x`.
  At least one failure is expected. Restore with `git checkout -- <file>`.
  A survivor gets a new killing test (red first) and a rerun.

| # | file · function | mutation |
|---|---|---|
| M1 | reference · build_reference | the closing point is not appended |
| M2 | samples · classify_driver | pit windows are ignored |
| M3 | source · inputs_from_rows | all location samples go into the first driver's bucket |
| M4 | gate · evaluate_gate | p95 `>` threshold becomes `>=` |
| M5 | timing_lines · measure_lines | lap 1 is not excluded |
| M6 | timing_lines · measure_lines | pit-adjacent laps are not excluded |
| M7 | state · state_at | the STALE branch interpolates |
| M8 | state · state_at | no unwrap across the finish line |
| M9 | reference · reference_candidates | the sort key drops the driver/lap tie-break |
| M10 | source · inputs_from_rows | the identity guard is removed |
| M11 | samples · classify_driver | OFF_REFERENCE samples get a fraction |
| M12 | builder · build_spatial | an uncited circuit falls back to 4259.0 m |
| M13 | spatial_store | the cache key omits the builder version |
| M14 | source · inputs_from_rows | conflicting duplicates keep the first |
| M15 | track_geometry · point_at | a closed loop clamps instead of wrapping |

- [ ] **Step 2: Performance.** `scripts/bench_spatial.py` measures, on the
  recording:
  - the cold build (caches deleted, `get_track_bytes`);
  - the cache load (a fresh store);
  - `state_at` latency, median and p95, over 1,000 seeded-random t inside
    the race;
  - `tracemalloc` peak during `read_index`.

  Run it and record the numbers in the validation doc.
- [ ] **Step 3: Documentation.**
  - `docs/PHASE_12_SPATIAL_INTELLIGENCE.md` (12A) covers: geometry source,
    coordinate system, spatial model, alignment, confidence, provenance,
    API, limitations, failure modes, testing and performance.
  - `CLAUDE.md` gets the 12A state, the commands (`spatial_report.py`,
    `bench_spatial.py`), next step 12B, and the baseline.
- [ ] **Step 4: Full verification.** Run
  `./.venv/Scripts/python.exe -m pytest tests -q`. Expect the previous 813
  passed plus the new tests, 5 skipped, and 1 failed (the known 10.3 S2
  check, from the uncommitted fixture), and report the exact counts. Run
  ruff on every changed file: 0 findings.
- [ ] **Step 5: Commit** with the message `phase12: 12A mutation results, performance and documentation`.
