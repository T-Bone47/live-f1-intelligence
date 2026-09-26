# Page override — Race Intelligence Command Center (`/`)

Overrides MASTER.md where it speaks; otherwise MASTER §13 applies.

## Layout

| width | composition |
|---|---|
| ≥ 1440 | `timing (38fr) · chart + battles (40fr) · focus (22fr)`, then `strategy (2 cols) · race control + weather` |
| 1024–1439 | `timing · chart / battles`, then `focus · strategy`, race control, weather |
| 760–1023 | one column: timing, focus, chart, battles, strategy, race control, weather |
| < 760 | recomposed: session header, then tabs Timing (tower + focus) / Race (chart + battles) / Strategy / Events (race control + weather) |

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
- Selecting a race-control message or a pit stop moves the cursor to the
  first frame that includes it.
- Keyboard: Space/K, ←/→, Home/End, ↑/↓ (tower), Enter, Esc, `?`.
