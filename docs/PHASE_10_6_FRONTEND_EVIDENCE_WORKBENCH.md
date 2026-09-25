# Phase 10.6 — Evidence Workbench (frontend)

The first user-facing consumer of `evidence_v1`. It answers "where did A
gain or lose time relative to B, and what evidence supports that?" by
**rendering, formatting and navigating** the Phase 10.5 evidence. It never
measures anything.

- Route: `/evidence` (lazy chunk, REST only; it never opens the live session
  socket). Linked from the pit-wall header ("EVIDENCE").
- Design source: `design-system/live-f1-intelligence/MASTER.md` plus
  `pages/evidence-workbench.md`.
- Backend changes: **none**. One dev script was added:
  `scripts/serve_evidence_dev.py`.

## Run it locally

```powershell
docker run -d --rm --name f1intel-test-pg -e POSTGRES_USER=f1intel -e POSTGRES_PASSWORD=f1intel_dev -e POSTGRES_DB=f1intel -p 5432:5432 postgres:16
cd backend; .\.venv\Scripts\python.exe ..\scripts\serve_evidence_dev.py   # seeds the real pair, serves :8000
cd ..\frontend; npm run dev                                               # http://localhost:5173/evidence
```

The script seeds the real Singapore pair (the unmodified OpenF1 rows) into its
**own** database, `f1intel_evidence_dev`, which it creates if needed.
- It never uses the test database: a persistent `(openf1, 9161)` session row
  there breaks the DB tests on the sessions unique key. This was found during
  this phase.
- The live route returns `ev1_a531c75484766ad06547e707`, the golden's id.
  The body is byte-identical to `docs/evidence/evidence_v1_singapore.json`
  apart from that file's trailing newline.

## Architecture

```
GET /evidence/lap-comparison ─► src/evidence/api.ts (classify HTTP, fail closed)
      ─► useEvidence (server state) ─► buildView (lookups only) ─► components
GET segment.telemetry_references[] ─► only on "Inspect telemetry" (RAW, existing route)
```

| layer | file | role |
|---|---|---|
| contract | `src/evidence/types.ts` | TS mirror of `app/evidence/schema.py`. The only description of the contract on the frontend. |
| request | `src/evidence/request.ts` | form ⇄ URL ⇄ API. Mirrors `validate_request` / `validate_session_id` (input hygiene only). |
| API | `src/evidence/api.ts` | 422/404/500/429/5xx/network → typed `EvidenceError`, backend message verbatim. Rejects a 200 body that is not evidence_v1, or whose `X-Evidence-Id` disagrees with the body. Follows only same-origin `/api/v1/sessions/{sid}/telemetry/{n}` references and checks drill-down identity. |
| format | `src/evidence/format.ts` | units, signs and phrasing the contract defines. Non-finite values render `—`. |
| vocabulary | `src/evidence/vocabulary.ts` | fixed labels for every enum. A test forbids causal words. |
| view | `src/evidence/viewModel.ts` | label/id maps, pinned limitations, the `normalized` flag. No values are derived. |
| seam | `src/evidence/racewise.ts` | `buildRaceWiseHandoff(evidence)` passes evidence_v1 unchanged. Disabled unless `VITE_RACEWISE_ENABLED=true`. |
| page | `src/components/evidence/EvidenceWorkbench.tsx` | owns the URL-backed request, server state and UI state |

**Components** (`src/components/evidence/`):
- `ComparisonForm`, `ComparisonHeader`, `DeltaChart`, `SegmentTimeline`;
- `SegmentInspector` with `EngineeringEvidence`;
- `DrilldownTelemetry`, `SectorEvidence`, `AccountingSummary`;
- `ProvenancePanel`, `LimitationsPanel` / `CaveatStrip`, `EvidenceStates`,
  `RaceWiseButton`;
- `primitives` (icons, `DriverTag`, `ClassBadge`, `SignificanceBadge`,
  `StatusBadge`, …) and `chartGeometry`.

**State.**
- Server state: `useEvidence(request)`: idle → loading (keeps the previous
  evidence, dimmed) → success | error. The evidence object is never mutated.
- UI state: selected segment label, drill-down open, selector open.
- URL: request parameters plus `seg`. The page can be shared and survives a
  reload, including a reload during loading.
- No state library was added.

## What the frontend does not do

It computes no delta, synchronization, interpolation, uncertainty,
significance, segmentation, attribution, accounting or confidence.
Specifically:
- **Significance** styling reads the `significant` flag.
  - Test: tamper R09 to `significant: true` although |−0.066| < 0.108; the
    UI shows "Significant".
- **Gap leaving** shows `delta_end_s`.
  - Test: tamper R09 `delta_end_s = 0.5`; the UI shows +0.500 s, not
    inherited + change.
- **Boundary metres** come from `distance_start_m` / `distance_end_m`, not
  x × length.
- **Offsets** use the contract's own difference fields. "earlier/later"
  applies the contract rule "sign A − B along the lap".
- **Gear and DRS** values are shown and never compared or subtracted in the
  UI.

The only arithmetic is pixel geometry (scales, ticks) and, in the drill-down,
seconds since each reference start, which is used to plot raw timestamps.

## Visualization

**Δt vs normalized lap distance** (hand-rolled SVG, matching the existing
`TelemetryLab`; no chart library added).

What is drawn:
- **Points** are Δt at segment boundaries, which is all evidence_v1 carries:
  `inherited_gap_s` at `x_start` and `delta_end_s` at `x_end`.
- **Chords** join the points and are labelled **"not a measured curve"**:
  dashed when not significant, solid `--confirmed` when significant.
- **Uncertainty band**: each segment draws `inherited_gap_s ± uncertainty_s`,
  hatched. A chord that stays inside it is a change that is not significant.
  The band only *shows* the contract rule; styling still comes from the flag.
- **Region tints and labels** ("#63 ahead ▲", "#55 ahead ▼") follow the sign
  convention. Red and green are never used for gain and loss.

Markers:
- the official lap Δ (class B) at x = 1.0, drawn as a separate marker and
  never joined to the engine curve;
- S1/S2 official line ticks per driver, from `line_x_a` / `line_x_b`;
- for the selected segment: the ½-change midpoint, the braking zone, and
  onset ticks (titled "temporal association").

Axis and interaction:
- **Axis**: "normalized lap distance — not track position". There is no
  circuit map, corner name or apex.
- **Interaction**: hover snaps to the nearest boundary point (tooltip:
  x, metres norm., Δt, who is ahead); click selects a segment.
- **Focus**: "Focus selection" tweens the x-domain to the selection and its
  neighbours over 220 ms (instant under reduced motion). "Full lap" and
  "Reset view" undo it.
- **Accessibility fallback**: a visually hidden table lists Δt at every
  boundary.

**Segment timeline.** One row per segment: range (m norm.), gap entering,
change, ±band, a change-vs-band gauge (the hatched track is always the band,
so "inside the track" reads "within band"), and significance plus status in
words.

**Drill-down.**
- Fetched only on click, from the segment's `telemetry_references`, with
  `frequency=RAW` and `fields=speed,throttle,brake,gear,drs` (no GPS).
- The time axis is seconds since each driver's own reference start. The panel
  says **"Not distance-aligned"**.
- Samples are drawn with visible markers. A synchronized cursor across the
  five channels reads the *nearest stored sample*, never an interpolation.
- Results are cached per reference URL.
- Verified against the live route: 5 channels, 390 sample markers
  (39 RAW samples × 5 channels × 2 drivers).

## Design system

The UI UX Pro Max workflow was applied by hand to its data files (the scripts
are not installed here). See MASTER.md §1:
- style: Data-Dense Dashboard with a Swiss grid, dark;
- fonts: "Developer Mono", i.e. JetBrains Mono (existing) for numbers,
  IBM Plex Sans for text, IBM Plex Sans Condensed for labels (all scoped to
  `.ewb`);
- charts: line with confidence band, waterfall-style accounting;
- rejected: HUD/Sci-Fi and Real-Time Monitoring styles.

Tokens:
- `tokens.css` gains a semantic layer (additive; nothing renamed):
  `--bg-*`, `--text-muted-aa`, `--border-*`, `--driver-*-ink`,
  `--delta-*-ahead`, `--confirmed`, `--uncertain`, `--historical` (class B),
  `--derived` (class C), `--unavailable` (class F) and `--telemetry-*`.
- **No color alone**: drivers use an A monogram (solid circle) and B
  (dashed square); significance, evidence class, NO_DATA and resolvable all
  carry words.

## Responsive and accessibility

Verified in the browser against the real API.

**Widths checked**: 375, 768, 1024, 1440, 1920. At each one, the
`.ewb` scrollWidth is at most the viewport width.
- **≥ 1280**: two columns with a sticky inspector.
- **Below 1280**: one column; order is chart → timeline → inspector →
  drill-down → sectors.
- **Below 760**: timeline rows drop range, entering and band.

Two real overflow bugs were found at 375 px and fixed:
- Implicit `auto` grid tracks grew to the chart SVG's width. Fixed with
  `minmax(0, 1fr)`.
- A visually hidden `<table>` ignores `width: 1px`. It is now wrapped in a
  hidden `<div>`.

Keyboard:
- Timeline rows: roving tabindex, ↑/↓/←/→, Home/End, Esc.
- Chart: ←/→ and Esc.
- Global: `[` and `]` step through segments.
- A skip link, focus rings (2 px), and 44 px targets on coarse pointers.

Other:
- `aria-pressed` on rows and chips, `role=alert` on errors, and
  `aria-busy` while loading.
- `prefers-reduced-motion` is honored: the global token rule plus the tween
  guard.

## Testing

In `frontend/tests/evidence/`: 114 tests; the full frontend suite is 165
(51 of them pre-existing). Everything runs against the real golden file
`docs/evidence/evidence_v1_singapore.json`.

| file | covers |
|---|---|
| `contract.test.ts` | TS field names of 11 models and 5 enums equal `evidence_v1.schema.json`; golden uses only known enums |
| `format.test.ts` | never null/NaN/Infinity; sign convention; who is ahead; offset rule; "norm."; vocabulary has no causal words |
| `request-api.test.ts` | request validation; URL round trip; swap; HTTP classification; fail-closed body and id checks; drill-down route whitelist and identity |
| `workbench.test.tsx` | the page on real evidence: every segment, significance and band; normalized labels; S3 NOT_COVERED; all limitations; provenance; no recomputation (two tampering cases); selection; keyboard; URL; no telemetry before a click; RAW drill-down; 422/404/500; unavailable fields; swap; RaceWise disabled |

**Mutation check:** 11 of 11 killed. Each was applied alone and restored.
- recompute significance; flip delta sign; flip offset rule; flip who is
  ahead; recompute delta_end;
- drop the evidence-id check; eager telemetry fetch; drop the "norm." label;
- render null as text; un-whitelist the telemetry route; drop `seg` from the
  URL while loading.

**Machine note:** on this machine the default 12-worker run can exhaust RAM
(`JavaScript heap out of memory` in tinypool workers). With
`npx vitest run --no-file-parallelism` everything passes. This is an
environment limit, not a test failure.

## Performance

- Evidence is at most 13 segments and the drill-down about 400 points: SVG,
  with no Canvas or WebGL.
- `DeltaChart`, `SegmentTimeline` and the drill-down traces are `memo`.
  Boundaries, y-extent and the view are memoized.
- Resize is coalesced to one update per frame (ResizeObserver plus rAF).
- Bundle: the workbench is a lazy chunk of 75.9 kB (22.7 kB gzip) JS plus
  32.0 kB CSS. The pit-wall entry is unchanged in behavior.

## Limitations and known gaps

- **No stored-laps listing route exists**, so the selector takes typed ids.
  The one validated real pair is offered as a preset. A `GET /sessions` for
  stored sessions and laps would enable pickers; it is a backend change and
  out of scope.
- The drill-down is time-based; aligning it to the evidence's distance axis
  would require recomputing 10.1B in the browser, so it is not attempted.
- `source.event` is `null` in the fixture and is shown as "Event not
  recorded".
- IBM Plex is loaded from Google Fonts. With no network the UI falls back to
  system sans.

## RaceWise handoff

`InvestigateWithRaceWiseButton` is visible but disabled, with the text
"integration contract is not finalized". When `VITE_RACEWISE_ENABLED=true`
and an `onHandoff` is wired, it passes
`{contract_version, evidence_type, evidence_id, focus_segment_ids, evidence}`
with the evidence unchanged. There is no network call and no simulated
response.
