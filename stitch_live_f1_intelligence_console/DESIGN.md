---
name: Obsidian Telemetry
colors:
  surface: '#111418'
  surface-dim: '#121317'
  surface-bright: '#37393d'
  surface-container-lowest: '#0c0e11'
  surface-container-low: '#1a1c1f'
  surface-container: '#1e2023'
  surface-container-high: '#282a2d'
  surface-container-highest: '#333538'
  on-surface: '#e2e2e6'
  on-surface-variant: '#e9bcb5'
  inverse-surface: '#e2e2e6'
  inverse-on-surface: '#2f3034'
  outline: '#af8781'
  outline-variant: '#5e3f3a'
  surface-tint: '#ffb4a8'
  primary: '#ffb4a8'
  on-primary: '#680200'
  primary-container: '#e10600'
  on-primary-container: '#fff2f0'
  inverse-primary: '#c00500'
  secondary: '#a0caff'
  on-secondary: '#003259'
  secondary-container: '#0063a9'
  on-secondary-container: '#c7deff'
  tertiary: '#dbb8ff'
  on-tertiary: '#480082'
  tertiary-container: '#914add'
  on-tertiary-container: '#fcf1ff'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdad4'
  primary-fixed-dim: '#ffb4a8'
  on-primary-fixed: '#410100'
  on-primary-fixed-variant: '#930300'
  secondary-fixed: '#d2e4ff'
  secondary-fixed-dim: '#a0caff'
  on-secondary-fixed: '#001c37'
  on-secondary-fixed-variant: '#00497e'
  tertiary-fixed: '#efdbff'
  tertiary-fixed-dim: '#dbb8ff'
  on-tertiary-fixed: '#2b0052'
  on-tertiary-fixed-variant: '#650db1'
  background: '#121317'
  on-background: '#e2e2e6'
  surface-variant: '#333538'
  surface-elevated: '#171b21'
  surface-hover: '#1c2128'
  border-subtle: '#1e232b'
  border-strong: '#2a313b'
  text-primary: '#e2e6eb'
  text-secondary: '#9aa3af'
  text-muted: '#5c6570'
  sector-purple: '#b26bff'
  sector-green: '#30d158'
  sector-yellow: '#ffd60a'
  tyre-soft: '#ee3f3d'
  tyre-medium: '#f5d563'
  tyre-hard: '#d0d0d0'
  tyre-inter: '#43b02a'
  tyre-wet: '#3a7bd5'
  critical: '#ff453a'
  warning: '#ffb340'
typography:
  display-title:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 24px
    letterSpacing: 0.12em
  headline-panel:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.18em
  body-base:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 19px
  body-dense:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 15px
  timing-tabular:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '600'
    lineHeight: 18px
    letterSpacing: -0.01em
  timing-tabular-lg:
    fontFamily: JetBrains Mono
    fontSize: 17px
    fontWeight: '700'
    lineHeight: 20px
  label-micro:
    fontFamily: Inter
    fontSize: 9px
    fontWeight: '600'
    lineHeight: 12px
    letterSpacing: 0.1em
  badge-caps:
    fontFamily: Inter
    fontSize: 10px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.08em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  gutter: 10px
  margin-screen: 10px
---

## Brand & Style
The design system is modeled after the high-stakes environment of a Formula 1 pit wall. It prioritizes information density, technical precision, and split-second situational awareness over decorative aesthetics. The brand personality is clinical, authoritative, and engineered, designed for professional-grade motorsport intelligence.

The visual style is **Corporate / Modern** with a **High-Density Technical** twist. It rejects "soft" design trends like large border radii or generous whitespace. Instead, it utilizes a "Graphite & Obsidian" layered approach—using micro-contrasts in dark shades and razor-thin borders to define structure. Motion is restrained, used only to indicate live data updates or state transitions, ensuring the user remains calm and focused during high-pressure race sessions.

## Colors
The palette is rooted in a "Dark-First" philosophy to minimize eye strain and maximize the pop of semantic F1 signals.

- **Foundational Layers**: Use `#0a0c0f` for the global canvas and `#111418` for primary data panels. Depth is achieved via 1px hairline borders (`#1e232b`) rather than shadows.
- **Semantic Precision**: F1-specific colors (Purple, Green, Yellow) are reserved strictly for sector performance and timing. Never use these for UI decoration.
- **Data Traces**: The Primary Red is reserved for "Live" status and the Lead Driver (Driver A), while the Secondary Blue is used for "Replay" mode and the Comparison Driver (Driver B).
- **Tyre Compounds**: Use the specific regulated hues for tyre chips and stint timelines to ensure immediate recognition by technical users.

## Typography
Typography is the most critical component of this design system's precision.

1.  **Tabular Alignment**: Every timing metric (gaps, lap times, telemetry units) must use the `timing-tabular` role. This utilizes JetBrains Mono to ensure that numbers do not "jump" or shift horizontally during live updates.
2.  **Case & Tracking**: Panel headers and micro-labels use uppercase with expanded tracking (0.1em - 0.18em) to create a technical, "instrument cluster" feel.
3.  **Hierarchy**: Primary data points (Position, Gap) should use high-contrast white, while metadata (units, labels) should be stepped down to `--text-secondary` or `--text-muted`.
4.  **Mobile Scaling**: For mobile views, the `timing-tabular-lg` role scales down to 14px to prevent horizontal overflow in compact timing towers.

## Layout & Spacing
This system uses a **Fixed Grid** model optimized for 1920x1080 "Pit Wall" displays. The dashboard is intended to be a single-viewport application, not a scrolling page.

- **Grid Model**: A 3-column asymmetric CSS Grid. 
    - Left (Timing Tower): `minmax(320px, 1.1fr)`
    - Center (Telemetry/Circuit): `2fr`
    - Right (AI/Strategy): `1fr`
- **Density**: Use a strict 4px spacing rhythm. Gutters are kept at 10px to maximize information density without elements touching. 
- **Responsive Reflow**: On Tablet, the center and right columns stack, while the timing tower remains pinned. Mobile views switch to a single-column layout focusing on the timing tower and AI Engineer console, with telemetry accessible via tabs.

## Elevation & Depth
Depth is communicated through **Tonal Layers** and **Subtle Outlines**. Avoid shadows entirely.

- **Surface 0 (Background)**: `#0a0c0f` — Used for the app canvas.
- **Surface 1 (Panels)**: `#111418` — Used for all primary content widgets.
- **Surface 2 (Interactive)**: `#171b21` — Used for selected states, active rows, or tooltips.
- **Hairline Borders**: Every panel must have a 1px border of `#1e232b`. Active or focused panels use a stronger `#2a313b` border. This creates a "machined" look, where panels feel like they are physical modules slotted into a rack.

## Shapes
The shape language is rigid and industrial. 

- **Corners**: Use a "Soft" (0.25rem / 4px) radius for primary panels and cards.
- **Micro-elements**: Small components like tyre chips and status badges use a 2px radius. 
- **Interactive States**: Buttons and inputs should maintain a consistent 4px radius.
- **Pills**: Only use full "pill" rounding for tyre compound indicators and session state tags (LIVE/REPLAY) to help them stand out from the rectangular grid of the UI.

## Components

### Timing Tower
- **Density**: Row height should be no more than 28px.
- **Indicators**: Use small triangles (▲/▼) for position changes.
- **Coloring**: Highlight `BEST` and `LAST` cells with background fills of `--sector-purple` or `--sector-green` at 20% opacity with a 100% opacity text label.

### Telemetry Traces
- **Waveforms**: Render on a `#0d1013` grid with `#1e232b` 0.5px grid lines.
- **Crosshair**: A vertical 1px dashed line that tracks the mouse/scrub across all synchronized traces (Speed, Throttle, Brake).

### AI Race Engineer Console
- **Structure**: Styled as a terminal window. Use a monospace font for "Evidence" chips like `[PACE-14]`.
- **Status**: A pulsing "Ready" or "Analyzing" dot in the header.
- **Input**: A minimalist text field with a 1px border, no background, and the label "ASK THE ENGINEER...".

### Tyre Chips
- **Design**: A circular dot of the compound color (Soft/Medium/Hard) followed by the stint length (e.g., "S | 12").

### Interactive Triggers
- **States**: Buttons should have no background fill in their default state—only a border. On hover, apply a subtle `#1c2128` fill. On active/selected, use `#171b21` with a `--text-primary` label.