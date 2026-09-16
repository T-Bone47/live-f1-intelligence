# UX LIMITATIONS — RE-CHECKED AGAINST HEAD

> Source list: `docs/ANTIGRAVITY_CURRENT_STATE.md`, items 1–17 (generated
> 2026-08-24, one commit before this phase's work began). Every verdict
> below is grounded in a direct read of the current source at the commit
> this file was written against (`03ed068` + this doc's own commit) —
> not inferred from the original list's description.

| ID | Previous limitation | Current status | Evidence | Remaining work | Priority |
|---|---|---|---|---|---|
| 1 | No driver selection propagation | FIXED | `TimingTower` reads `selectDriver`/`selectedDriver` from the shared `useDriverSelection()` store (`state/store.ts`), not a no-op prop | none | — |
| 2 | No driver comparison | FIXED | `TelemetryLab` reads real `comparisonDriver` from the same shared store and fetches/renders driver B's traces | none | — |
| 3 | No session-mode adaptation | FIXED | `App.tsx` has 6 distinct layout functions (Race/Qualifying/Telemetry/Strategy/DriverFocus/Minimal) with genuinely different panel sets, not one layout reused | none | — |
| 4 | Timing tower missing columns | FIXED | Header row has P/Δ/DRV/TEAM/GAP/INT/LAP/LAST/BEST/S1/S2/S3/TYRE/PACE; TEAM and PACE are collapsed behind an `isExpanded` toggle (deliberate, not a gap) | none | — |
| 5 | No circuit map | STILL_OPEN | `CircuitMap` shows a position-order strip, honestly labeled "CIRCUIT GEOMETRY UNAVAILABLE — POSITION ORDER SHOWN" — no fabricated coordinates | needs a real geometry source (F1DB investigation, explicitly greenfield in the original 57-section spec, not this phase) | P2 |
| 6 | No tyre strategy timeline in main layout | FIXED | `TyreStrategyTimeline` renders in `RaceLayout` and `StrategyLayout`; fixed for real data this phase (was rendering all stints at 0 width) | none | — |
| 7 | No "Race Picture" summary | FIXED | Renders for race/focus/qualifying presets; weather bugs inside it fixed this phase | none | — |
| 8 | No live event rail (RC-only) | FIXED | `RCFeed` now has a real ALL/RC/TIMING/BATTLE/TYRE/STRATEGY filter set (categories corrected this phase), not RC-only | none | — |
| 9 | No data freshness indicators | FIXED | `DataFreshness` rendered in the session header, driven by connection status | none | — |
| 10 | No replay controls | STILL_OPEN | `grep -rl "replay" frontend/src/components` — zero matches, confirmed | backend supports play/pause/speed (`/api/v1/replay/{id}/control`) with no frontend consumer at all | P1 |
| 11 | No qualifying-specific UI | PARTIALLY_FIXED | Was wrongly marked FIXED earlier in this phase -- `QualifyingCutLine` gated on `snap?.profile`, which never existed (same root cause as the weather/session_type bugs), so it could never render under any circumstances; fixed to gate on the real `session_type` field. It renders now, but its Q1/Q2/Q3 cutoff-position logic keys off `snap.phase`, a race-control state enum (`LIVE`/`SUSPENDED`/`RED_FLAG`/`SAFETY_CAR`/`VSC`/`CHEQUERED`/...) with no Q1/Q2/Q3 concept in it at all -- so it always shows the Q1 (P15) cutoff regardless of the actual segment | no Q1/Q2/Q3 sub-phase signal exists anywhere in the current backend; needs new tracking, not a field-name fix -- real feature work, correctly out of scope for this phase | P2 |
| 12 | No practice-specific UI | FIXED | Same `snap?.profile` bug as #11, same fix (gate on `session_type`) -- `PracticeClassification`'s own logic (splitting short/long runs) doesn't depend on any further unmodeled state, so this one is genuinely complete once the gate is correct | none | — |
| 13 | No responsive layout | PARTIALLY_FIXED | 3 real breakpoints now exist (`768px`, `1100px`, `2000px` ultrawide) plus a `prefers-reduced-motion` query — up from the single breakpoint originally described | breakpoint behavior confirmed to exist in CSS, not independently verified rendered at each size in this pass | P3 |
| 14 | CSS duplication (`styles.css`/`tokens.css` conflicts) | FIXED | `styles.css` defines zero root custom properties (`grep -c "^  --"` → 0); its only `:root` block is a deliberate override nested inside the `2000px` media query, not a duplicate/conflicting base definition | none | — |
| 15 | Font loading (no `@font-face`/Google Fonts) | FIXED | `tokens.css` imports Inter + JetBrains Mono from Google Fonts directly and wires them into `--font-sans`/`--font-mono` | none | — |
| 16 | No navigation rail | FIXED | Rail exists and — as of this phase — actually functions (was previously present but inert; see the NavRail commit) | none | — |
| 17 | Stitch design not integrated | PARTIALLY_FIXED | Fonts and CSS tokens are wired through (items 14/15); the Stitch HTML itself remains a standalone reference file, not systematically diffed against every component | no component-by-component design-spec conformance pass has been done | P3 |

**Summary: 11 FIXED, 4 PARTIALLY_FIXED, 2 STILL_OPEN, 0 NOT_REPRODUCIBLE.**
Both STILL_OPEN items (circuit geometry, replay controls) require real new
frontend surface area, not bug fixes — correctly out of scope for a phase
whose brief is "make the existing product stable," not build new UI.

**Correction, same phase, later pass:** item 11 was originally marked
FIXED in this table. While writing Phase H's tests for `QualifyingCutLine`
directly, I found it gated on `snap?.profile` — a field that never
existed — so it could never render at all, under any session type. This
table's original verdict was written from "the component exists and is
wired into the layout," which turned out not to be sufficient evidence;
correcting it here rather than leaving a wrong verdict standing.
