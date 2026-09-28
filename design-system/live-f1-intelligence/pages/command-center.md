# Page override — Race Intelligence Command Center (`/`)

Overrides MASTER.md where it speaks; otherwise MASTER §13 applies.

## Layout

| width | composition |
|---|---|
| ≥ 1440 | `timing (38fr) · track map + chart + battles (40fr) · focus (22fr)`, then `strategy (2 cols) · race control + weather` |
| 1024–1439 | `timing · track map / chart / battles`, then `focus · strategy`, race control, weather |
| 760–1023 | one column: timing, focus, track map, chart, battles, strategy, race control, weather |
| < 760 | recomposed: session header, then tabs Timing (tower + focus) / Track (map) / Race (chart + battles) / Strategy / Events (race control + weather) |

The track map's height follows its width (0.8 × width, 220–540 px); the
SVG is sized to the panel, never wider (Phase 12B).

The replay bar is fixed at the bottom on every width (two rows under
760 px). The app bar is sticky; below 900 px its nav takes a second row.
The page is its own scroll container (`.cc`).

## Timing tower columns

Priority: position, driver, gap > interval, tyre > lap, last, stops >
best, sectors. Columns drop by the panel's own width (container queries:
< 560 px hides sectors and best, < 470 px hides lap, last and stops).
Compact density hides the secondary columns at any width.

## Interaction

- Selecting a driver (row, chart line, stint row) opens driver focus and
  highlights the driver everywhere.
- Selecting a battle marks both rows and opens the interval history.
- Selecting a race-control message moves the cursor to the message's own
  time; selecting a pit stop moves it to the first frame that includes it.
- The cursor is race time (Phase 12B). ←/→ step lap frames; Shift+←/→ move
  10 s; the scrubber runs over seconds; rates are 1×/4×/16×/64× race time.
- Frame-row panels (timing, positions, battles, strategy) say which frame
  they show: "as of LAP k · hh:mm:ss".
- Track map: hover or focus a car for its tooltip; click or Enter selects it
  (the same selection as the tower); ↑/↓ move through cars in position
  order; Esc clears. Clicking a timing line shows its measured p95 and n.
- Keyboard: Space/K, ←/→, Shift+←/→, Home/End, ↑/↓ (tower, map), Enter,
  Esc, `?`.
