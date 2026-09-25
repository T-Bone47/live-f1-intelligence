# RaceWise Evidence Contract — `evidence_v1`

**Boundary.** Live F1 Intelligence (LFI) *measures*: it acquires, normalizes,
synchronizes and attributes, then returns structured evidence. RaceWise
*reasons*: it investigates, forms hypotheses, falsifies them and concludes.
LFI never returns conclusions, and RaceWise never needs to know how
distances are integrated or how uncertainty is computed.

- Machine schema: `docs/evidence/evidence_v1.schema.json`, exported from
  `app/evidence/schema.py`.
- Real example: `docs/evidence/evidence_v1_singapore.json`, byte-locked by
  a test.

## 1. Endpoint

`GET /api/v1/sessions/{session_id}/evidence/lap-comparison`

The response body is canonical JSON bytes, with these headers:
- `X-Evidence-Contract: evidence_v1`
- `X-Evidence-Id: <evidence_id>`
- `Server-Timing: db, pipeline, serialize` (durations in ms)

The same rate limit applies as for every other `/api/v1` route.

## 2. Request parameters

| param | type | rule |
|---|---|---|
| `driver_a`, `driver_b` | int | car numbers 1–99 |
| `lap_a`, `lap_b` | int | ≥ 1. `driver_a/lap_a` ≠ `driver_b/lap_b`. Both laps come from `{session_id}`, so cross-session comparison is impossible by construction and also refused in the builder. |
| `lap_length_m` | float | finite and > 0. **Required**: there is no circuit geometry, and a length is never guessed. |
| `lap_length_source` | str | printable citation of 1–300 characters, echoed in the evidence |
| `contract_version` | str | default `evidence_v1`; anything else returns 422 |

## 3. Response schema (top level)

| field | meaning |
|---|---|
| `contract_version` | `"evidence_v1"` |
| `evidence_type` | `"lap_comparison"` |
| `evidence_id` | stable content id (§8) |
| `calculation` | `evidence_builder_version`, `attribution_version`, `lap_distance_version`, `contract_version` |
| `source` | `provider`, `session_id`, `session_type`, `season`, `event`, `circuit`. `null` means not recorded, never guessed. |
| `comparison` | `driver_a`, `driver_b` (lap, duration, `started_at`, telemetry coverage and channel availability); `lap_delta_s`; `sign_convention`; `lap_length`; `alignment`; `telemetry_confidence` |
| `attribution.segments[]` | straight-to-straight segments in lap order (§5) |
| `attribution.accounting` | exact decomposition of the covered delta change (§7) |
| `attribution.sectors[]` | official sector deltas and engine sector changes, reported separately (§5) |
| `limitations[]` | `{code, message}`. The codes are the machine contract (§10). |
| `provenance` | `chain`, `input_digest`, `identity_checks`, per-lap telemetry ranges (§8) |

Evidence classes reuse the project's `ProvenanceClass` letters:
- **B**: historical observation (official timing).
- **C**: deterministic derivation (engine values).
- **F**: unavailable.

## 4. Sign convention

`delta_t = elapsed_A − elapsed_B`; **negative means A is ahead**.
`accumulated_change_s = delta_end − delta_start`:
- positive: A lost time in the segment;
- negative: A gained time in the segment.

Swapping A and B negates every change; this is property-tested.

## 5. Segment semantics

A segment runs from peak speed on one straight to peak speed on the next,
so every corner lies inside one segment.

**Time fields**

| field | meaning |
|---|---|
| `inherited_gap_s` | delta at the segment start. It already existed; it was **not** caused here. |
| `accumulated_change_s` | the *new* change inside the segment. Do not add it to `inherited_gap_s` to "explain" the gap. |
| `uncertainty_s` | the band the change must exceed; `significant = abs(change) > uncertainty`. |
| `direction` | `LOSING` / `GAINING` / `RECOVERING` (gaining while starting behind) / `STABLE` (not significant) / `NO_DATA` |

**`attribution_status`**

| status | meaning |
|---|---|
| `SINGLE_CONTROL_INPUT` | significant, and exactly one control-input family differs resolvably |
| `MULTI_SIGNAL` | significant, and several families differ. **No primary is named.** |
| `SPEED_ONLY` | significant, and only speed differs beyond alignment error |
| `INSUFFICIENT_EVIDENCE` | significant, but nothing is resolvable |
| `NOT_SIGNIFICANT` | there may be evidence of differences, but **not** enough to attribute time |
| `NO_DATA` | no telemetry coverage |

**Signal fields**
- `primary_signal` is **the single control-input family that differed
  resolvably**, not a cause. It is `null` unless the status is
  `SINGLE_CONTROL_INPUT` or `SPEED_ONLY`.
- `onset_order[]` lists signals in lap order, each with
  `relation_to_midpoint` (BEFORE / AFTER / AT the point where half the
  change had accumulated).
- The evidence blocks (`braking`, `throttle`, `speed`, `gear`, `drs`) carry
  offsets in metres, with sign A − B along the lap.
  - `*_resolvable` is true only when the two drivers' sample brackets are
    further apart than the misalignment bound.
  - Gear and DRS are compared for equality only and never subtracted.

**Provenance and drill-down**
- `telemetry_references[]` points at the **existing** route
  `GET /api/v1/sessions/{sid}/telemetry/{driver}?start=&end=` for
  drill-down. Evidence never embeds raw telemetry.

**Sectors** (`attribution.sectors[]`)
- `official_delta_s` (class B) and `engine_change_s` (class C) are
  separate numbers.
- `coverage = NOT_COVERED` (engine `null`) when telemetry does not reach
  the sector line. No sector value is manufactured.

## 6. Significance semantics

- `significant` and `attribution_status` are exactly Phase 10.4's values.
  The contract validator rejects any payload where they disagree with
  `abs(change) > uncertainty`.
- **"There is evidence"** (resolvable offsets, gear differences) is
  different from **"there is enough evidence to attribute time"**
  (`significant: true`). A `NOT_SIGNIFICANT` segment can still carry
  resolvable control-input differences.
- `uncertainty_s` rests on the misalignment **measured** at the official
  sector lines (`comparison.alignment.misalignment_bound_m`). Two anchors
  per lap make it a lower bound (`UNCERTAINTY_ANCHORS_LOWER_BOUND`).

## 7. Association semantics and accounting

- Every association is `TEMPORAL_ASSOCIATION`. The schema allows no other
  value and rejects extra fields such as `cause`.
- "Brake onset preceded the accumulation midpoint" is evidence.
  "Braking late caused the loss" is a RaceWise conclusion.

Accounting:

```
attributed_change_s + unattributed_significant_change_s + below_significance_change_s
    == actual_change_s          (validated to 1e-9; segment changes also sum to actual)
unaccounted_s == actual_change_s − attributed_change_s
```

## 8. Provenance and identifiers

**Chain:** `evidence_v1` → `attribution-x.y.z` → 10.2 `DeltaSample.delta_t_s`
→ `lap-distance-x.y.z` → canonical `Lap` / `TelemetryCarSample` → provider
rows (identity-guarded).

**Per segment:** grid index range, real-sample index ranges and timestamp
ranges per driver.

**Identifiers** (deterministic; no UUIDs, no wall-clock times, no array
positions):

| identifier | definition |
|---|---|
| `input_digest` | `sha256` over the canonical input rows (laps and every telemetry sample) |
| `evidence_id` | `"ev1_" + sha256([contract, attribution_version, lap_distance_version, session, drivers, laps, lap_length_m, lap_length_source, input_digest])[:24]`. The same data and versions give the same id; new data or a new algorithm gives a new id. |
| `segment_id` | `"{evidence_id}:g{grid_start}-{grid_end}"` |
| `sector_id` | `"{evidence_id}:S{n}"` |

The validator recomputes all of these, so a tampered id is rejected.

## 9. Calculation version

`calculation.attribution_version` names the 10.4 algorithm, and the builder
maps only the versions it knows (`SUPPORTED_ATTRIBUTION_VERSIONS`). A new
10.4 version **fails closed** (HTTP 500, evidence withheld) until the
mapping is reviewed, so an algorithm change can never silently re-label old
semantics. RaceWise should key any cache on `evidence_id`.

## 10. Limitations (structured)

| code | consequence for reasoning |
|---|---|
| `ALIGNMENT_NORMALIZED_DISTANCE` | metres are integrated distance ÷ cited length, not physical track position |
| `ALIGNMENT_POSITION_PROJECTED_UNVALIDATED` | only if Phase 10.3 traces are used (never by this endpoint) |
| `UNCERTAINTY_ANCHORS_LOWER_BOUND` | "significant" = not explained by the *measured* misalignment |
| `UNCERTAINTY_WITHIN_SEGMENT_PROVISIONAL` | D = E, calibrated on one real pair |
| `UNCERTAINTY_DEFAULT_PROVISIONAL` / `UNCERTAINTY_SINGLE_ANCHOR` | no or partial official sector anchors |
| `BRAKE/THROTTLE/GEAR/DRS_CHANNEL_MISSING` | that comparison is absent. Absent is **not** "did not brake". |
| `TELEMETRY_COVERAGE_INCOMPLETE` | `NO_DATA` spans exist; nothing is attributed there |
| `INTRA_SEGMENT_SPLITS_LESS_CERTAIN` | braking before/during/after and per-phase splits are less certain than totals |
| `THROTTLE_CALIBRATION_DIFFERS` | mean throttle differences include per-car calibration (99 vs 100) |
| `DRS_SEMANTICS_UNVERIFIED` | DRS codes are compared raw; do not read "open" or "closed" into them |
| `NO_TRACK_GEOMETRY` | no apex, corner name or corner identity exists |
| `ASSOCIATION_NOT_CAUSATION` | associations are temporal only |

## 11. Error behavior

| HTTP | when |
|---|---|
| 422 | a missing or invalid parameter; unsupported `contract_version`; a lap without a duration; no stored telemetry; cross-session or identity-guard failure |
| 404 | unknown session, lap or driver |
| 500 | the evidence failed `evidence_v1` validation. **It is withheld; it is never returned as valid.** |

Nothing is ever substituted: not another lap, driver or session, and not a
guessed length.

## 12. Example response (excerpt of the real golden file)

```json
{
 "contract_version": "evidence_v1", "evidence_type": "lap_comparison",
 "evidence_id": "ev1_a531c75484766ad06547e707",
 "calculation": {"attribution_version": "attribution-1.1.0", "contract_version": "evidence_v1",
                 "evidence_builder_version": "evidence-builder-1.0.0",
                 "lap_distance_version": "lap-distance-1.0.0"},
 "source": {"circuit": "Singapore", "event": null, "provider": "openf1", "season": 2023,
            "session_id": "openf1:9161", "session_type": "Qualifying"},
 "comparison": {"lap_delta_s": -0.07200000000000273,
                "sign_convention": "delta_t = elapsed_A - elapsed_B; negative means A is ahead",
                "alignment": {"mode": "NORMALIZED_DISTANCE",
                              "misalignment_bound_m": 4.307640288355742,
                              "uncertainty_source": "SECTOR_LINE_ANCHORS"}, "...": "..."},
 "attribution": {
  "segments": [{
   "segment_id": "ev1_a531c75484766ad06547e707:g582-688", "label": "R09",
   "distance_start_m": 2875.08, "distance_end_m": 3398.72,
   "inherited_gap_s": 0.08407756334359817, "accumulated_change_s": -0.0658604943400718,
   "uncertainty_s": 0.10835170049057002, "significant": false, "direction": "STABLE",
   "attribution_status": "NOT_SIGNIFICANT", "primary_signal": null,
   "association": "TEMPORAL_ASSOCIATION",
   "onset_order": [{"signal": "brake_onset", "family": "brake", "distance_m": 2899.67,
                    "relation_to_midpoint": "BEFORE", "association": "TEMPORAL_ASSOCIATION"}],
   "braking": {"onset_offset_m": 31.81833333333349, "onset_offset_resolvable": true,
               "paired": true, "...": "..."},
   "gear": {"min_a": 2, "min_b": 3, "difference_fraction": 0.29906542056074764, "...": "..."},
   "telemetry_references": [{"driver_number": 55, "lap_number": 19,
     "route": "/api/v1/sessions/openf1:9161/telemetry/55",
     "start": "2023-09-16T14:27:34.368000+00:00", "end": "2023-09-16T14:27:45.087000+00:00"}]
  }],
  "accounting": {"actual_change_s": -0.09661302634827962, "attributed_change_s": 0.0,
                 "unattributed_significant_change_s": 0.0,
                 "below_significance_change_s": -0.09661302634827962,
                 "unaccounted_s": -0.09661302634827962, "...": "..."},
  "sectors": [{"sector": 3, "official_delta_s": -0.09699999999999775,
               "official_provenance_class": "B", "engine_change_s": null,
               "engine_provenance_class": "F", "coverage": "NOT_COVERED", "...": "..."}]
 },
 "limitations": [{"code": "ALIGNMENT_NORMALIZED_DISTANCE", "message": "..."}, "..."]
}
```

Values are unrounded 10.4 floats. Presentation rounding belongs to the
client.

## 13. Example investigation flow

RaceWise is asked: *"Why did Russell (#63) lose time to Sainz (#55) on
their best Singapore Q3 laps?"*

1. **RaceWise → LFI:**
   `GET …/evidence/lap-comparison?driver_a=55&lap_a=19&driver_b=63&lap_b=16&lap_length_m=4940&lap_length_source=…`
2. **LFI returns evidence only.** It contains:
   - `lap_delta_s = −0.072` (B, official): #55 ahead.
   - Sectors: S1 −0.068, S2 +0.093, S3 −0.097 (B).
   - 12 segments, **all `NOT_SIGNIFICANT`** against the measured 4.31 m
     misalignment.
   - Resolvable differences: R09 brake onset +31.8 m (#55 later), R09
     minimum gear 2 vs 3, R02 brake onset −29.6 m.
   - 9 limitation codes.
3. **RaceWise forms hypotheses.** H1: "#63 lost the lap in the final
   sector." H2: "#63 lost time braking into R09."
4. **RaceWise evaluates the evidence.**
   - H1 is supported by S3 −0.097 (class B, official), but the engine
     cannot localise it: S3 is `NOT_COVERED`, and the R10–R12 changes lie
     within uncertainty.
   - For H2: R09's change is −0.066 ± 0.108, `NOT_SIGNIFICANT`. The later
     braking and 2nd gear are *temporal associations* only.
5. **RaceWise falsifies.** H2 cannot be confirmed at segment level: the
   evidence says the change is within measured uncertainty. It is not
   contradicted either; it is unresolved.
6. **RaceWise concludes**, in its own words with its own confidence, citing
   `evidence_id` and `segment_id`s. LFI took no part in steps 3–6.
