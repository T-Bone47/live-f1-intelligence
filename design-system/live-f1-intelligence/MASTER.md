# Live F1 Intelligence — Design System MASTER

The authoritative design source for the frontend. Page files in `pages/`
may override a rule for one page; where they are silent, this file applies.

The system is **Obsidian Telemetry** (`frontend/src/design/tokens.css`,
first described in `stitch_live_f1_intelligence_console/DESIGN.md`), which
Phase 10.6 extends with evidence semantics. There is still one token file
and one design system.

## 1. How this was derived

The UI UX Pro Max workflow (github.com/nextlevelbuilder/ui-ux-pro-max-skill)
was run by hand against its data files, because the skill's scripts are not
installed in this environment:

| domain | UI UX Pro Max row | decision |
|---|---|---|
| product type | BI / analytics, engineering tool | a dense workstation, not a landing page |
| style | #28 Data-Dense Dashboard, with #1 Swiss grid discipline and #7 Dark Mode | dark-first, hairline rules, 8 px gaps, minimal padding, maximum data visibility |
| style rejected | #51 HUD / Sci-Fi FUI | high accessibility risk, and glow and scan effects compete with the data |
| style rejected | #31 Real-Time Monitoring | explicitly "not for historical analysis"; evidence is historical |
| typography | "Developer Mono" (JetBrains Mono + IBM Plex Sans) | mono for every number, Plex for text, Plex Sans Condensed for labels |
| charts | #1 line over a continuous axis; #9 line with a confidence band; #13 waterfall for cumulative change | Δt over normalized distance, with an uncertainty band per segment |
| UX rules | focus states, color-only, reduced motion, excessive motion, content jumping, truncation | listed in §8 and §9 |

## 2. Visual direction

**An engineering instrument, not a dashboard template.** It should read like
a calibrated test-bench readout: dark field, thin rules, tabular figures,
labels set small in condensed capitals, and color reserved for meaning.

Target character: dark-first, high density, precision, editorial
engineering, subtle depth (surface steps, never shadows), strong hierarchy,
fast scanning and controlled motion.

## 3. Color: semantic tokens

Components use semantic tokens only; no raw hex in components. The
primitives live in `tokens.css`, and the Phase 10.6 semantic layer maps onto
them.

| token | role |
|---|---|
| `--bg-primary` / `--bg-secondary` / `--bg-panel` / `--bg-elevated` / `--bg-hover` | surface steps from the page to a hovered row |
| `--text-primary` / `--text-secondary` / `--text-muted-aa` / `--text-disabled` | `--text-muted-aa` passes 4.5:1 on panels; the legacy `--text-muted` is for decoration only |
| `--border-subtle` / `--border-default` / `--border-emphasis` | hairlines, then separators, then selection |
| `--driver-a` / `--driver-b` | line and fill color for each driver |
| `--driver-a-ink` / `--driver-b-ink` | text color for each driver, AA on panels |
| `--delta-a-ahead` / `--delta-b-ahead` | which side of zero Δt is on. **Never good or bad.** |
| `--positive` / `--negative` / `--neutral` | numeric sign only |
| `--confirmed` | significant: the change exceeds its uncertainty band |
| `--uncertain` | the uncertainty band, and not-significant state |
| `--warning` | limitations, withheld evidence |
| `--historical` | evidence class B, official timing |
| `--derived` | evidence class C, engine calculation |
| `--unavailable` | evidence class F, NO_DATA |
| `--telemetry-speed` / `-throttle` / `-brake` / `-gear` / `-drs` | channel family accents |

**Never color alone.** Every semantic color is paired with another cue:

| meaning | other cues |
|---|---|
| driver | an "A"/"B" monogram; A is a solid line with a round marker, B is a dashed line with a square marker |
| significance | the words `SIGNIFICANT` / `NOT SIGNIFICANT`, plus solid vs dashed chords |
| evidence class | a lettered badge: `B OFFICIAL`, `C DERIVED`, `F UNAVAILABLE` |
| NO_DATA | hatching plus the words `NO DATA` |
| resolvable | the word `RESOLVABLE` / `WITHIN ALIGNMENT ERROR` |

**Delta color rule.** Red and green are **not** used for gain and loss. A
negative Δt means A is ahead, so it takes A's hue; a positive Δt takes B's.
The sign is always printed, together with a "#55 ahead" phrase.

## 4. Typography

| role | family | size / weight | notes |
|---|---|---|---|
| numbers (times, deltas, metres, kph, ids) | JetBrains Mono | 11–22 px, 500–700 | `tabular-nums`, with signs always shown on deltas |
| labels, eyebrows, column heads | IBM Plex Sans Condensed | 10–11 px, 600, +0.08em, caps | dense but not tiny; never below 10 px |
| body, explanations | IBM Plex Sans | 12–13 px, 400–500 | sentence case, 1.45 line height |
| key figure (lap Δ) | JetBrains Mono | 28 px, 700 | one per view |

No marketing type, no hero sizes. Line length for prose is 72ch at most.

## 5. Spacing, radius, depth

- 4 px rhythm (`--sp-*`). Panel padding is 12 px; gaps between panels are
  8 px on desktop and 12 px on mobile.
- Radius is 2–4 px. No pills except status chips.
- Depth comes from surface steps and 1 px borders only. No drop shadows, no
  glass, no glow.

## 6. Component principles

- A container fetches and owns server state; presentation components
  receive typed props and never fetch. The one exception is the explicit
  telemetry drill-down.
- One concept, one component: `EvidenceStatusBadge`, `ClassBadge` and
  `DriverTag` are used everywhere.
- Components stay under about 200 lines, and split when they grow.
- Every value passes through a formatter that renders `Unavailable` / `—`,
  never `null`, `undefined`, `NaN` or `Infinity`.

## 7. Chart principles

- Axis titles carry units and meaning. A Δt axis always states its sign
  convention.
- The x-axis is **normalized lap distance**: never "track position", no
  corner names, no circuit outline.
- Uncertainty is drawn, not hidden in tooltips. Non-significant change is
  visually muted.
- Draw only what the contract carries. If a curve is not in the contract,
  say so on the chart rather than drawing a smooth line.
- Proximity is not causality. Onset markers are labelled as temporal
  associations.
- Use SVG for fewer than 1,000 points (this includes every evidence_v1
  chart). Move to Canvas only when profiling shows a need.
- Every chart has a text or table fallback for screen readers.

## 8. Interaction and accessibility

- Every control is a real `<button>`, `<input>` or `<a>`, with a visible 2 px
  focus ring (`--border-focus`).
- Lists of selectable items use a roving tabindex: arrow keys move,
  Home/End jump, and Escape clears.
- Touch targets are at least 32 px on desktop and 44 px on coarse pointers.
- Text is at least 10 px. Contrast is 4.5:1 for text and 3:1 for chart
  strokes.
- Icons are inline SVG (Lucide-derived). **No emoji as functional icons.**
  Icon-only buttons carry an `aria-label`.
- Live regions announce loading and errors (`aria-busy`, `role=status`,
  `role=alert`).

## 9. Motion

- Motion tokens: `--transition-fast` (100 ms), `--transition-normal`
  (180 ms), `--transition-slow` (300 ms).
- Animate state changes only: a selection moving, the chart focusing, a
  panel expanding. One or two animated elements per view.
- No pulsing, spinning decoration, bouncing, or entrance choreography on
  data.
- `prefers-reduced-motion: reduce` removes all transitions and tweens; the
  final state is always correct without animation.

## 10. Responsive

| width | composition |
|---|---|
| ≥ 1280 | two columns: analysis (chart, timeline, sectors) and a sticky inspector |
| 768–1279 | one column; chart full width; inspector follows the timeline |
| < 768 | recomposed: summary → chart → segment chips → inspector → drill-down → sectors → caveats → provenance |

There must be no horizontal page scroll at 375 px. Tables become row cards,
and chips wrap.

## 11. Anti-patterns (rejected)

- Generic SaaS KPI-card grids, purple gradients, glassmorphism, neon glow.
- Red and green for "good" and "bad" deltas.
- A decorative circuit map, "corner 7" labels, or apex markers without
  geometry.
- Rewriting evidence states into causal prose ("braked too late").
- Tooltips as the only home for uncertainty or limitations.
- Rendering `null`, `NaN` or `undefined`.

## 12. F1-specific visual language

- Driver identity is `#NN` with an A/B monogram, and never a hard-coded name
  or team color.
- Lap times are shown as `m:ss.sss`, deltas as signed seconds to 3 decimals
  (ms precision), and change and band values also to 3 decimals.
- Sectors are S1, S2 and S3. Official sector values carry class B; engine
  values carry class C.

## 13. Phase 11 — Race Intelligence Command Center

The hero surface. Everything above applies; this section adds what a
multi-panel, time-scrubbed workstation needs. Page override:
`pages/command-center.md`.

**Visual north star.** Pit wall plus engineering workstation: deep tonal
surfaces, hairline rules, tabular numerals, one accent per meaning. Premium
comes from precision and alignment, not effects. No glow, no glass panels
(only the two chrome bars use a light backdrop blur over scrolling content),
no gradients except one faint top wash on the page root.

**Tokens (tokens.css, Phase 11 layer).**

| group | tokens | rule |
|---|---|---|
| elevation | `--background-root < -inset < -panel < -elevated < -hover < -selected` | depth is tonal; no shadows |
| state | `--state-live / -replay / -historical / -warning / -danger / -success / -neutral / -unknown` | LIVE red only with the word and a connected socket |
| flags | `--flag-green / -yellow / -red / -sc / -vsc / -blue / -chequered` | always with the flag's word or icon |
| tyres | `--tyre-soft / -medium / -hard / -intermediate / -wet / -unknown` | ring + letter + word; unknown is dashed |
| selection | `--focus-ink`, `--selection-rule` | neutral: selection is never a driver colour or a verdict |
| radius | `--radius-row` 2 px < `--radius-panel` 6 px < `--radius-surface` 10 px | pills only for filter chips |
| motion | `--motion-fast` 120 / `-normal` 200 / `-slow` 320 / `-exit` 140 ms; `--ease-standard / -emphasized / -exit` | enter slower than exit; spatial moves emphasized |

**Driver identity.** A 3 px bar in the provider's team colour + the
three-letter code + the number. Team colour comes from the data
(`team_colour`), never a hard-coded map; the second car of a team is dashed
in charts. Identity colour never encodes gain or loss.

**Typography.** Display: IBM Plex Sans Condensed 700, uppercase, 26 px
(session title, lap counter in JetBrains Mono 700). Labels: Plex Condensed
600, 10.5–12 px, +0.08em. Numbers: JetBrains Mono, tabular. Body: Plex Sans
13 px. Nothing below 10 px.

**Motion (only state changes).** Timing rows glide to a new position (FLIP,
transform, 320 ms emphasized); a changed gap tints for 320 ms; panels reveal
with a 4 px rise; the nav and tab indicators slide; the scrubber fill
follows the cursor. No pulsing, no looping animation except the loading
shimmer. All of it is removed under `prefers-reduced-motion`.

**States.** Every panel has loading (content-shaped skeleton), empty (what
is missing, why) and error (what failed, retry) states. Missing values are
"—" or a word, never 0.

**Truth rules specific to the command center.**
- One cursor, one moment: no panel may read a different frame.
- Official text is quoted verbatim (race control) and marked `B OFFICIAL`;
  engine values are marked `C DERIVED`.
- Not in the data = said so: DRS availability, undercut/overcut, scheduled
  distance, retirement status, event name.
- No track map, corner names or "track position" from normalized distance.
