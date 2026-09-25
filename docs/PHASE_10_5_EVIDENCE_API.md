# Phase 10.5 — Evidence API (`evidence_v1`)

**Live F1 Intelligence = evidence engine. RaceWise = reasoning engine.**
This phase adds a versioned, validated, deterministic evidence contract on
top of Phase 10.4. It adds no LLM, no reasoning and no new analytics. The
consumer-facing specification is `docs/RACEWISE_EVIDENCE_CONTRACT.md`; this
document covers engineering.

## Architecture

```
10.1B lap_distance -> 10.1C lap_comparison -> 10.2 delta_analysis -> 10.4 attribution
   -> 10.5 app/evidence (restructure + validate + identify + serialize) -> evidence_v1 API
   -> RaceWise (investigation)  /  10.6 UI (presentation)
```

| file | role |
|---|---|
| `app/evidence/schema.py` | pydantic v2 models (`extra=forbid`, `strict`, `allow_inf_nan=False`), cross-field validators, deterministic id functions, JSON Schema export |
| `app/evidence/lap_comparison.py` | request/input validation; the 10.4 report → evidence mapping (pure restructure, floats unrounded); `input_digest`; canonical serialization; `parse_evidence` |
| `app/api/__init__.py` | `GET /api/v1/sessions/{sid}/evidence/lap-comparison`; `_load_session_source`. It reuses the 10.4 loader `_load_lap_telemetry`. |

**No duplicated mathematics.**
- Every analytical value is read from the 10.4 report, or from the
  10.1B/10.1C trace objects it was computed from (coverage, sample counts,
  trace confidence). Nothing is recomputed.
- `tests/test_evidence_real.py` asserts exact float equality with a direct
  10.4 run on the real pair.
- The `values rounded` and `uncertainty dropped` mutations are killed.

**10.4 change needed (additive, no numeric change).**
- 10.4 carried limitations only as free text, so it now also emits
  `limitation_items` (`LimitationCode` + message) and per-driver
  `channels` availability. Gear, throttle and DRS channels were previously
  unflagged.
- `CALC_VERSION` moves to `attribution-1.1.0`. A diff of the regenerated
  real-pair report against 1.0.0, ignoring version and new fields, is
  **identical**.

## Schema

See `docs/evidence/evidence_v1.schema.json` (exported) and the contract
doc §3.

**Fail-closed validation** (each item has a test):
- **Strict types:** `"0.1"` for a number and `1.0` for an integer are
  rejected, as are unknown fields (e.g. `cause`) and NaN/Infinity.
- **Significance consistency:** `significant == abs(change) > uncertainty`.
  STABLE ⇔ not significant. LOSING needs change > 0; GAINING/RECOVERING
  need change < 0; RECOVERING needs an inherited deficit. A NO_DATA segment
  carries no data.
- **Accounting:** the parts equal actual (1e-9), `unaccounted` equals
  actual − attributed, and segment changes sum to actual.
- **Identity:**
  - `evidence_id`, `segment_id` and `sector_id` are recomputed from content.
  - Telemetry references may point only to the compared drivers and laps.
  - Provenance laps and session must match the comparison and source.
- **Structure:** segments are contiguous and ordered, and sector
  `segment_ids` must exist. `coverage == COVERED` if and only if an engine
  value exists.
- **Versions:** `contract_version` is Literal `evidence_v1`. The builder
  maps only `SUPPORTED_ATTRIBUTION_VERSIONS`.

## Determinism and serialization

- **Canonical bytes:** sorted keys, no whitespace, UTF-8, Python
  shortest-repr floats (unrounded), `null` for unavailable, enums as their
  string values, and no NaN.
- **IDs** are content hashes; wall-clock time never enters the body.
  `Server-Timing` is a header, not body.
- **Verified:**
  - the golden file is byte-identical across reruns;
  - repeated API requests are byte-identical;
  - serialize → parse → serialize is byte-identical.

## Real Singapore validation

`docs/evidence/evidence_v1_singapore.json`: 60,763 bytes,
`ev1_a531c75484766ad06547e707`.

- 13 segment entries: 12 straight-to-straight segments plus the NO_DATA
  tail after x = 0.981.
- **0 significant**, exactly as in 10.4.
- E = 4.307640288355742 m (`SECTOR_LINE_ANCHORS`).
- Accounting: actual −0.09661302634827962 s = attributed 0 +
  below-significance −0.0966 s.
- The resolvable R02/R09 brake onsets, the R09 gear 2 vs 3 and the throttle
  full/application offsets remain available.
- 9 limitation codes. S3 is `NOT_COVERED`.
- `source.event` is `null`: the fixture records no meeting name.

## API

See the contract doc §1–2 and §11.
- **Reuse:** the 10.4 `/attribution` route stays as it was (unversioned,
  engine-shaped, for internal inspection). RaceWise must use
  `/evidence/lap-comparison`.
- **Backward compatibility:** `/attribution` and `/telemetry/compare` are
  exercised by `test_existing_routes_keep_their_contracts`.

## Performance

Measured with `scripts/bench_evidence.py`, real pair, local Postgres 16,
TestClient:

| measure | ms |
|---|---:|
| cold request (first in process; includes lazy imports) | 256.3 |
| warm request, median of 15 | 136.1 |
| — db (pool creation + 3 queries) | 82.1 |
| — pipeline (10.1B→10.4 + evidence build + validation) | 46.7 |
| — serialize (canonical JSON) | 1.8 |

**Caching: not added.**
- The dominant cost is the API-wide pool-per-request convention (the same
  as `/telemetry`), which is out of scope.
- A correct cache key needs the `input_digest`, which requires reading the
  rows anyway, and compute is 47 ms.
- `evidence_id` is already the correct key if a cache is ever justified by
  load.

## Testing

| file | tests | covers |
|---|---:|---|
| `test_evidence_contract.py` | 50 | serialization and round trip; versions; stable ids; nulls; unrounded 10.4 equality; significance/association/recovery propagation; structured limitations; no raw telemetry; **negative cases 1–15**; **19 payload tampering cases** |
| `test_evidence_real.py` | 5 | real pair vs direct 10.4 (every segment, sector and accounting value); verified properties; golden bytes plus round trip plus schema; determinism |
| `test_evidence_properties.py` | 30 | 15 scenario × sampling cases: sign convention, accounting, ordering, no streams, identity, determinism; A/B swap negates |
| `test_evidence_api.py` | 3 | **route bytes == builder bytes on real rows through real Postgres**; repeat determinism; 11 HTTP failure cases; backward compatibility |
| `test_attribution.py` (+5) | 29 | structured limitation and channel additions in 10.4 |

**Source mutations** (`app/evidence/*`): 14 of 14 killed.
- driver identity, sample identity guard, sign convention, significance
  validation, uncertainty and value rounding;
- accounting validation (survived at first; the new `accounting parts`
  tamper case now kills it), input digest in the id, positional segment id;
- any contract version accepted, future attribution version accepted,
  limitations dropped, cross-session allowed, and NO_DATA marked as
  observed.

## Fresh-context review (answers)

1. **Consumable without internals?** Yes. The fields are documented
   semantically (contract doc), and no algorithm knowledge is needed.
2. **Can the UI consume it?** Yes (see the 10.6 handoff below).
3. **Raw telemetry leaking?** No. Numeric arrays are ≤ 16 long
   (property-tested); drill-down is a reference only.
4. **Fabrication?** `null` / class F / NOT_COVERED / channel flags cover
   everything unavailable; `event` is null.
5. **Significance changed?** Values pass through, and the validator
   rejects inconsistency.
6. **Causal meaning?** Association is a Literal and extra fields are
   forbidden. `primary_signal` is documented as "the differing family, not
   a cause" (a review finding; wording made explicit).
7. **Provenance?** chain, `input_digest`, per-segment grid/sample/ts
   ranges, and per-lap coverage.
8. **Version explicit?** Four version strings.
9. **Deterministic?** Yes, verified three ways.
10. **Another provider?** Yes. `input_digest` is over canonical models, not
    provider rows, and `source.provider` is a free field.
11. **10.4 changes?** They fail closed via `SUPPORTED_ATTRIBUTION_VERSIONS`,
    and `evidence_id` changes with the version.
12. **10.3 optional?** Yes. It is never used by the endpoint; if position
    traces are used, the limitation code
    `ALIGNMENT_POSITION_PROJECTED_UNVALIDATED` applies.

## Phase 10.6 handoff

The UI consumes the same `evidence_v1` and never re-derives anything:

| UI element | evidence field |
|---|---|
| summary | `comparison.lap_delta_s`, `alignment.mode` / `misalignment_bound_m`, `accounting` |
| delta strip | segments' `x_start`/`x_end` with `inherited_gap_s` → `delta_end_s` |
| significance | `significant`, `direction` (show RECOVERING distinctly), `uncertainty_s` as an error band |
| signals | `onset_order`, `braking` / `throttle` / `speed` / `gear` / `drs`, with `*_resolvable` for emphasis |
| drill-down | `telemetry_references[]` → the existing `/telemetry/{driver}?start&end` route |
| caveats | `limitations[].code`; every metre label shows "normalized" when `ALIGNMENT_NORMALIZED_DISTANCE` is present |

## Future extension points

- New evidence types (stint, battle, pit) become new `evidence_type`s under
  the same envelope.
- Breaking changes go to `evidence_v2` in `SUPPORTED_CONTRACTS`.
- A 10.4 algorithm change means adding its version to
  `SUPPORTED_ATTRIBUTION_VERSIONS` after review.
- Once sector-anchored alignment is validated, the new alignment mode and
  source flow through `comparison.alignment`.
