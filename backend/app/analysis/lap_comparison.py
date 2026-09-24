"""Phase 10.1C: driver A/B lap comparison service.

Wraps the Phase 10.1B lap-distance engine into a single, ready-to-use
comparison between two drivers' laps: real telemetry -> lap extraction ->
distance integration -> normalization -> synchronized telemetry -> delta-t.

This is deliberately a thin orchestration layer, not a second engine.
Every step delegates directly to app.analysis.lap_distance
(build_lap_distance_trace, normalize_lap, synchronize_drivers, delta_t) -
none of that logic is reimplemented here. Same reasoning as 10.1B reusing
app.analysis.confidence/app.analysis.laps rather than duplicating them:
one canonical implementation per concept in this project.

Scope boundary (explicit, per the Phase 10.2 prompt's own framing of what
10.1C provides vs. what 10.2 adds): this module gets to a synchronized
comparison with delta_t at any point, including start/finish convenience
accessors. It does NOT scan the delta curve for maximum gain/loss or
segment it into gaining/losing regions - that is Phase 10.2's explicit
"deterministic engineering delta analysis" scope, not this one's.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.common.models import Confidence, LapClass
from app.analysis.lap_distance import (
    LapDistanceTrace,
    SynchronizedComparison,
    build_lap_distance_trace,
    confidence_rank,
    delta_t,
    normalize_lap,
    synchronize_drivers,
)
from app.core.models import Lap, TelemetryCarSample


@dataclass
class DriverLapComparison:
    """A complete, ready-to-use comparison between two drivers' laps.

    confidence is the worse of the two underlying traces' own confidence -
    a comparison is only as trustworthy as its least-trustworthy side; a
    clean HIGH-confidence pole lap compared against a degraded PIT_OUT lap
    is not itself a HIGH-confidence comparison.
    """

    session_id: str
    driver_a: int
    lap_number_a: int
    driver_b: int
    lap_number_b: int
    lap_length_m: float
    trace_a: LapDistanceTrace
    trace_b: LapDistanceTrace
    sync: SynchronizedComparison
    delta_at_start: float | None
    delta_at_finish: float | None
    confidence: Confidence


def compare_driver_laps(
    lap_a: Lap, samples_a: list[TelemetryCarSample], lap_class_a: LapClass | None,
    lap_b: Lap, samples_b: list[TelemetryCarSample], lap_class_b: LapClass | None,
    lap_length_m: float,
    step: float = 0.001,
) -> DriverLapComparison:
    """Build both drivers' distance traces, normalize, synchronize, and
    compute the basic delta accessors.

    lap_length_m is required from the caller, same as normalize_lap - this
    project has no circuit geometry to derive a lap length from yet (see
    docs/PHASE_10_1B_LAP_DISTANCE_SYNCHRONIZATION.md's known limitations),
    and inventing one here would be exactly the fabrication both this and
    the prior phase's prompts explicitly forbid. Both laps are normalized
    against the SAME lap_length_m - it is the caller's responsibility that
    this genuinely represents both laps' shared circuit; passing
    inconsistent values for what should be the same track is not detected
    here (documented as a known limitation, not silently guarded against).

    lap_a.session_id must equal lap_b.session_id - enforced by
    synchronize_drivers (raises ValueError otherwise), not re-implemented
    here.
    """
    trace_a = normalize_lap(
        build_lap_distance_trace(lap_a, samples_a, lap_class_a), lap_length_m)
    trace_b = normalize_lap(
        build_lap_distance_trace(lap_b, samples_b, lap_class_b), lap_length_m)

    sync = synchronize_drivers(trace_a, trace_b, step=step)

    overall_confidence = min((trace_a.confidence, trace_b.confidence), key=confidence_rank)

    return DriverLapComparison(
        session_id=lap_a.session_id, driver_a=lap_a.driver_number,
        lap_number_a=lap_a.lap_number, driver_b=lap_b.driver_number,
        lap_number_b=lap_b.lap_number, lap_length_m=lap_length_m,
        trace_a=trace_a, trace_b=trace_b, sync=sync,
        delta_at_start=delta_t(sync, 0.0), delta_at_finish=delta_t(sync, 1.0),
        confidence=overall_confidence,
    )


def delta_at(comparison: DriverLapComparison, x: float) -> float | None:
    """Elapsed-time delta between the two drivers at an arbitrary normalized
    distance x. Thin pass-through to app.analysis.lap_distance.delta_t -
    exists so a caller working with a DriverLapComparison doesn't need to
    know about the underlying SynchronizedComparison's shape directly."""
    return delta_t(comparison.sync, x)
