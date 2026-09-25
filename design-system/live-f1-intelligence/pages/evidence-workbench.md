# Page override — Evidence Workbench (`/evidence`)

MASTER.md applies except where this file says otherwise.

## Purpose

Answer "where did A gain or lose time relative to B, and what evidence
supports that?" using `evidence_v1` alone. The page renders, formats and
navigates the evidence. It never measures anything.

## Overrides

| rule | MASTER | this page | why |
|---|---|---|---|
| page scroll | the pit-wall shell locks `body` | `.ewb` is its own full-height scroll container | the workbench is a reading surface, not a fixed console |
| body font | Inter (pit wall) | IBM Plex Sans / Plex Sans Condensed, scoped to `.ewb` | the UI UX Pro Max "Developer Mono" pairing; the rest of the app is untouched |
| key figure | none | the official lap Δ at 28 px | the single number the page exists to explain |

## Signature element: the uncertainty band

Each segment draws a band spanning `x_start`–`x_end` and running from
`inherited_gap_s − uncertainty_s` to `inherited_gap_s + uncertainty_s`. The
chord to `(x_end, delta_end_s)` either stays inside the band
(`significant: false`) or leaves it (`significant: true`).

- The geometry only *shows* the contract's rule
  (`significant = |change| > uncertainty`). The styling is driven by the
  `significant` field itself, never recomputed.
- Chords are dashed and muted when not significant, and solid in
  `--confirmed` when significant.
- The chart states that Δt is known only at segment boundaries: the chords
  are not a measured curve.

## Layout

```
┌ bar: product · back to pit wall · comparison selector (collapsible) ───────┐
├ summary: #A card │ official lap Δ (B) · engine Δ at last covered x (C) │ #B ┤
├ caveat strip: normalized distance · association ≠ causation · lower bound ─┤
├───────────────────────────────────────────────┬────────────────────────────┤
│ Δt vs normalized lap distance (chart)          │ inspector (sticky ≥1280)    │
│ segment timeline (rows with a band gauge)      │  time accounting            │
│ telemetry drill-down (on demand)               │  interpretation state       │
│ sectors · accounting                           │  onset order · signals      │
├───────────────────────────────────────────────┴────────────────────────────┤
│ limitations (always open) │ provenance (collapsible)                        │
└────────────────────────────────────────────────────────────────────────────┘
```

## Vocabulary (fixed; never strengthened)

| contract value | UI label | secondary line |
|---|---|---|
| `NOT_SIGNIFICANT` | Not significant | Change lies within the uncertainty band. |
| `SINGLE_CONTROL_INPUT` | One control input differs | Exactly one input family differs resolvably. This is an association, not a cause. |
| `MULTI_SIGNAL` | Several inputs differ | No primary signal is named. |
| `SPEED_ONLY` | Only speed differs | No control input is resolvable. |
| `INSUFFICIENT_EVIDENCE` | Insufficient evidence | Significant, but nothing is resolvable. |
| `NO_DATA` | No data | No telemetry coverage. Nothing is attributed. |
| `RECOVERING` | Recovering | Gaining while starting behind. |

Offsets are phrased from the contract's sign rule (A − B along the lap):
"#55 brake onset 31.8 m later (norm.)". The words "because", "caused",
"better", "worse" and "mistake" never appear.

## Motion on this page

- The selected-segment highlight transitions its fill (`--transition-normal`).
- The chart x-domain tweens over 220 ms when focusing a segment. It is
  skipped under reduced motion.
- Nothing else animates.
