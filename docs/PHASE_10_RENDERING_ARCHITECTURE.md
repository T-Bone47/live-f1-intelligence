# PHASE 10 — RENDERING & CLOCK ARCHITECTURE

## Rendering, per surface (Rule 8)

Applied per target rather than as one blanket technology choice — the
research (`PHASE_10_DATA_AVAILABILITY.md`) established the general
thresholds; this applies them to this project's actual scale.

**Track map + car markers + trails → SVG.** The centerline (a resampled
lap trace, ~1000-2000 points), 2-22 car markers, and short rolling trails
are small relative to even the low end of the 3-5k-element threshold
multiple sources converge on. SVG's real advantage isn't just headroom at
this size — marker hover/click-to-select comes free via native DOM
events, directly matching this codebase's existing click-to-select
pattern (`TimingTower`). Canvas would mean reimplementing hit-testing by
hand for no benefit at this scale.

**Telemetry trace stack (speed/throttle/brake/gear/rpm) + delta graph →
Canvas, via `uPlot`.** Resampled onto the common distance grid
(`PHASE_10_LAP_SYNCHRONIZATION.md`), this is roughly 1000 points × 2
drivers × 5-6 channels — small in absolute terms, but a different access
pattern from the track map: several stacked panels sharing one
continuously-dragged scrubber cursor, redrawn every frame while
scrubbing. That's `uPlot`'s designed case specifically (benchmarked for
best-in-class cursor/zoom interactivity, DOCUMENTED via Rule 2 research),
and Canvas's clear-and-redraw model handles sustained high-frequency
redraw more predictably than SVG's DOM diffing at that rate. The delta
graph is one more panel on the same synchronized cursor, not a separate
technology.

**Event timeline → SVG/DOM.** A strip of maybe 10-30 discrete markers
(DRS zones, sector boundaries, braking points) along the distance axis —
same reasoning as the track map.

**WebGL: not recommended at this scope, explicitly rather than by
omission.** It becomes justified once the workload actually changes —
full 22-driver replay with dense simultaneous trails, or genuine
full-field 60fps animation (both named risks, architecture doc §9) — not
for the 2-driver flagship comparison. A real threshold to revisit
honestly if scope grows, not a permanent no.

## Clock architecture (Rule 5)

Not a single choice between extending `ReplayProvider`, introducing a new
clock, or a vague hybrid — the two use cases are different in kind, and
splitting by what each is actually for is the answer, not a compromise.

**`ReplayProvider` stays exactly what it is.** It is fundamentally
stateful and forward-only: it paces canonical envelopes into the same
`AnalysisEngine` live sessions use, and that engine's internal state
(personal bests, rolling pace windows, stint tracking, battle proximity)
accumulates incrementally from session start. Seeking this clock means
either replaying from t=0 at max speed to rebuild state, or checkpointing
engine state periodically — genuinely expensive either way. Reverse is
close to meaningless against a rolling average. This is the right tool
for "watch a past session as if live," and Rule 1's "one clock, all
consumers" requirement is already satisfied here: track/timing/events/
tyres/strategy/battles/AI already flow through one paced stream.

**A new, separate, purpose-built clock owns the bounded comparison
use case** — proposed name `LapReplayClock`, chosen precisely so it
doesn't read as competing with `ReplayProvider`. Two drivers, one lap,
telemetry only, with no rolling state to rebuild: once the persistence
wiring (architecture doc §4) lands, that data is a **bounded,
pre-fetchable array**. Seeking, reversing, and frame-stepping an index
into an array already in memory is trivial, not expensive. This clock
operates entirely client-side (or as a thin, stateless server helper)
over pre-fetched data, and never touches `AnalysisEngine` at all.

This mirrors something real from the research rather than an invented
split: ATLAS treats live and historical/replay data through *one
interface* at the "parameters and displays" level (DOCUMENTED, Rule 2),
but that's a UX unification, not a claim that one clock implementation
correctly serves every temporal use case underneath it. Same idea here,
one layer down: one coherent interaction model, two implementations
sized to what each actually needs to do.

**60fps note**: the render loop should interpolate smoothly between real
resampled telemetry points for visual quality — this is a rendering
concern, not a data claim. Real telemetry tops out near 3.5Hz; nothing
about a 60fps render loop implies 60Hz of measured data exists, and no
part of this design should be read as claiming otherwise.
