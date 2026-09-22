"""Tests for the core distance integration / lap-boundary / normalization
layer of the Phase 10.1B lap-distance engine.

Synthetic data throughout - these prove the algorithm's own mathematical
properties (does 100 km/h for 1 second cover 27.78m? does a regression
corrupt the running total?), which doesn't need real telemetry to prove.
tests/test_lap_distance_real_fixture.py separately proves the real-data
path end to end.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.common.models import Confidence, LapClass
from app.analysis.lap_distance import (
    MAX_GAP_S,
    build_lap_distance_trace,
    integrate_distance,
    normalize_lap,
)
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Lap, Provenance, TelemetryCarSample

PROV = Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.A)


def _sample(t: float, speed_kph: float | None, driver: int = 1) -> TelemetryCarSample:
    return TelemetryCarSample(
        session_id="test:session", driver_number=driver,
        ts=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=t),
        speed_kph=speed_kph, provenance=PROV,
    )


# --- 1. Basic constant-speed integration -----------------------------------

def test_constant_speed_integration_matches_exact_physics():
    # 100 km/h for 10 seconds = 100/3.6 m/s * 10s = 277.777...m, exactly.
    samples = [_sample(t, 100.0) for t in range(11)]
    points = integrate_distance(samples)
    assert points[-1].distance_m == pytest.approx(100.0 / 3.6 * 10.0, abs=1e-9)
    assert points[0].distance_m == 0.0


# --- 2. Variable-speed integration ------------------------------------------

def test_variable_speed_integration_uses_trapezoidal_average():
    # 0 -> 100 km/h over 1s, then 100 -> 0 over 1s: trapezoidal average
    # speed per interval is 50 km/h, so total = 2 * (50/3.6 * 1) = 27.777...m
    samples = [_sample(0, 0.0), _sample(1, 100.0), _sample(2, 0.0)]
    points = integrate_distance(samples)
    assert points[-1].distance_m == pytest.approx(2 * (50.0 / 3.6 * 1.0), abs=1e-9)


# --- 3. km/h -> m/s conversion ----------------------------------------------

def test_kph_to_mps_conversion_factor():
    # 360 km/h is exactly 100 m/s - a clean number to catch a wrong constant.
    samples = [_sample(0, 360.0), _sample(1, 360.0)]
    points = integrate_distance(samples)
    assert points[-1].distance_m == pytest.approx(100.0, abs=1e-9)


# --- 4. Timestamp ordering ---------------------------------------------------

def test_normal_ascending_timestamps_all_high_confidence():
    samples = [_sample(t, 200.0) for t in range(5)]
    points = integrate_distance(samples)
    assert all(p.confidence == Confidence.HIGH for p in points)


# --- 5. Duplicate timestamps --------------------------------------------------

def test_duplicate_timestamp_contributes_zero_distance_not_an_error():
    samples = [_sample(0, 100.0), _sample(0, 150.0), _sample(1, 150.0)]
    points = integrate_distance(samples)
    assert points[1].distance_m == points[0].distance_m  # zero-width interval
    assert points[1].confidence == Confidence.MEDIUM
    assert points[1].gap_s == 0.0


# --- 6. Timestamp regression --------------------------------------------------

def test_timestamp_regression_does_not_corrupt_or_reverse_distance():
    samples = [_sample(0, 100.0), _sample(2, 100.0), _sample(1, 999.0), _sample(3, 100.0)]
    points = integrate_distance(samples)
    dists = [p.distance_m for p in points]
    # never decreases, even across the regression
    assert dists == sorted(dists)
    # the regressed point itself contributes nothing and is flagged
    assert points[2].distance_m == points[1].distance_m
    assert points[2].confidence == Confidence.NONE
    assert points[2].gap_s < 0


# --- 7. Missing speed ----------------------------------------------------------

def test_missing_speed_holds_distance_flat_and_flags_none():
    samples = [_sample(0, 100.0), _sample(1, None), _sample(2, 100.0)]
    points = integrate_distance(samples)
    assert points[1].distance_m == points[0].distance_m
    assert points[1].confidence == Confidence.NONE
    # recovery: the interval from the missing-speed point onward also can't
    # integrate (needs both ends), so distance stays flat until speed returns
    assert points[2].distance_m == points[0].distance_m
    assert points[2].confidence == Confidence.NONE


# --- 8. Large telemetry gaps -----------------------------------------------

def test_gap_above_threshold_still_integrates_but_flags_low_confidence():
    samples = [_sample(0, 100.0), _sample(MAX_GAP_S + 10, 100.0)]
    points = integrate_distance(samples)
    assert points[1].distance_m > 0  # still the best available estimate
    assert points[1].confidence == Confidence.LOW
    assert points[1].gap_s == MAX_GAP_S + 10


def test_gap_at_or_below_threshold_stays_high_confidence():
    samples = [_sample(0, 100.0), _sample(MAX_GAP_S, 100.0)]
    points = integrate_distance(samples)
    assert points[1].confidence == Confidence.HIGH


def test_gap_threshold_is_grounded_in_real_data():
    """MAX_GAP_S must stay evidence-based, not driftable back to an
    arbitrary number - recomputes the real fixture's own inter-sample
    deltas on every run and checks the threshold's actual justification,
    rather than trusting the module docstring to stay accurate."""
    fixture = (Path(__file__).parent.parent.parent / "scripts" / "fixtures"
               / "real-openf1-9159" / "raw_car_data_source.json")
    with open(fixture) as f:
        rows = json.load(f)
    rows.sort(key=lambda r: r["date"])
    tss = [datetime.fromisoformat(r["date"]) for r in rows]
    deltas = [(tss[i] - tss[i - 1]).total_seconds() for i in range(1, len(tss))]
    normal = [d for d in deltas if d < 60]
    anomalous = [d for d in deltas if d >= 60]

    assert max(normal) < MAX_GAP_S, (
        "every genuinely continuous real interval must fall under the threshold")
    assert MAX_GAP_S < min(anomalous), (
        "the threshold must sit below the real dataset's actual gaps, not just above jitter")


# --- 9. Monotonic distance (property-style) --------------------------------

def test_distance_never_decreases_across_a_noisy_realistic_sequence():
    speeds = [0, 50, 120, 300, 280, 310, 40, 0, 0, 90, 200]
    samples = [_sample(i * 0.3, v) for i, v in enumerate(speeds)]
    points = integrate_distance(samples)
    dists = [p.distance_m for p in points]
    assert dists == sorted(dists)
    assert all(d >= 0 for d in dists)


# --- 10. Lap reset (distance does not leak across laps) --------------------

def test_distance_resets_per_lap_does_not_leak_into_next_lap():
    lap1 = Lap(session_id="s", driver_number=1, lap_number=1,
               started_at=datetime(2026, 1, 1, tzinfo=UTC),
               duration_s=10.0, provenance=PROV)
    lap2 = Lap(session_id="s", driver_number=1, lap_number=2,
               started_at=datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC),
               duration_s=10.0, provenance=PROV)
    all_samples = [_sample(t, 200.0) for t in range(21)]  # spans both laps fully

    trace1 = build_lap_distance_trace(lap1, all_samples, LapClass.REPRESENTATIVE)
    trace2 = build_lap_distance_trace(lap2, all_samples, LapClass.REPRESENTATIVE)

    assert trace2.points[0].distance_m == 0.0  # lap 2 starts fresh, not continuing lap 1's total
    assert trace1.total_distance_m == pytest.approx(trace2.total_distance_m, rel=1e-6)


# --- 11. Normalized distance -------------------------------------------------

def test_normalize_lap_produces_expected_fraction():
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    samples = [_sample(t, 360.0) for t in range(11)]  # 360kph = 100m/s, 10s -> 1000m
    trace = build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE)
    trace = normalize_lap(trace, lap_length_m=1000.0)
    assert trace.points[-1].normalized_distance == pytest.approx(1.0, abs=1e-6)
    assert trace.points[0].normalized_distance == pytest.approx(0.0, abs=1e-6)
    assert not trace.has_overshoot


def test_overshoot_is_flagged_not_clamped():
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    samples = [_sample(t, 360.0) for t in range(11)]  # integrates to 1000m
    trace = build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE)
    trace = normalize_lap(trace, lap_length_m=800.0)  # shorter than actual integration
    assert trace.points[-1].normalized_distance > 1.0  # NOT clamped to 1.0
    assert trace.points[-1].is_overshoot is True
    assert trace.has_overshoot is True
    assert trace.confidence == Confidence.MEDIUM  # downgraded from HIGH, not hidden


# --- 12. Zero-length lap -----------------------------------------------------

def test_zero_length_lap_does_not_divide_by_zero():
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    samples = [_sample(t, 200.0) for t in range(5)]
    trace = build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE)
    trace = normalize_lap(trace, lap_length_m=0.0)  # must not raise ZeroDivisionError
    assert all(p.normalized_distance is None for p in trace.points)
    assert trace.confidence == Confidence.NONE


# --- 13. Incomplete lap -------------------------------------------------------

def test_incomplete_lap_with_no_duration_returns_none_confidence_not_a_guess():
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=None, provenance=PROV)  # still in progress
    samples = [_sample(t, 200.0) for t in range(5)]
    trace = build_lap_distance_trace(lap, samples, LapClass.UNCLASSIFIED)
    assert trace.points == []
    assert trace.confidence == Confidence.NONE


# --- 14. Insufficient telemetry ----------------------------------------------

def test_too_few_samples_capped_at_medium_even_if_internally_consistent():
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    # 6 samples spanning the full 10s window, each exactly MAX_GAP_S apart
    # (2s - still HIGH per-interval, not LOW) so neither an internal gap
    # nor incomplete start/end coverage is in play - isolates the
    # sample-count ceiling from the other two ceilings, which have their
    # own dedicated tests.
    samples = [_sample(t, 200.0) for t in (0, 2, 4, 6, 8, 10)]
    trace = build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE)
    assert trace.is_complete is True
    assert trace.confidence == Confidence.MEDIUM


def test_telemetry_ending_well_before_lap_end_is_flagged_incomplete():
    """A lap classified REPRESENTATIVE with plenty of samples must still
    not look complete if the telemetry itself stops far short of the
    lap's actual end - found during self-review: sample COUNT alone
    doesn't guarantee the samples actually span the whole lap."""
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=60.0, provenance=PROV)
    # 15 samples, densely packed, but only covering the first 5 seconds
    # of a 60-second lap - the back 55 seconds have no telemetry at all.
    samples = [_sample(t * 0.3, 200.0) for t in range(16)]
    trace = build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE)
    assert trace.is_complete is False
    assert trace.confidence != Confidence.HIGH


# --- 20. Pit-lane / degraded handling ----------------------------------------

@pytest.mark.parametrize("lap_class", [LapClass.PIT_IN, LapClass.PIT_OUT, LapClass.IN_LAP])
def test_pit_laps_never_reach_high_confidence_even_with_clean_telemetry(lap_class):
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    samples = [_sample(t, 200.0) for t in range(15)]  # plenty, perfectly regular
    trace = build_lap_distance_trace(lap, samples, lap_class)
    assert trace.confidence != Confidence.HIGH
    assert trace.is_pit_lap is True


@pytest.mark.parametrize("lap_class", [LapClass.INVALID, LapClass.OUTLIER])
def test_invalid_outlier_laps_never_reach_high_confidence(lap_class):
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    samples = [_sample(t, 200.0) for t in range(15)]
    trace = build_lap_distance_trace(lap, samples, lap_class)
    assert trace.confidence != Confidence.HIGH


def test_representative_lap_with_clean_dense_telemetry_reaches_high_confidence():
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    samples = [_sample(t * 0.5, 200.0) for t in range(21)]  # 21 samples, regular
    trace = build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE)
    assert trace.confidence == Confidence.HIGH


# --- 21. Confidence propagation ----------------------------------------------

def test_one_bad_interval_downgrades_the_whole_trace_confidence():
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=20.0, provenance=PROV)
    samples = [_sample(t * 0.5, 200.0) for t in range(20)]
    samples.append(_sample(19.9, None))  # one missing-speed sample near the end
    trace = build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE)
    assert trace.confidence != Confidence.HIGH  # the one NONE-confidence point taints the roll-up


# --- 22. Deterministic repeated execution ------------------------------------

# --- Phase 15: property / invariant testing ----------------------------------
# hypothesis is not already a dependency of this project, so these are
# explicit deterministic cases across varied synthetic scenarios rather than
# a new property-testing framework (Phase 19: don't introduce one merely
# because it exists) - same invariants, no new dependency.

@pytest.mark.parametrize("speeds", [
    [100] * 10,
    [0, 50, 100, 150, 200, 150, 100, 50, 0],
    [300, 300, 0, 0, 300, 300],
    [10, 400, 10, 400, 10],  # unrealistic but not negative - must not break monotonicity
])
def test_invariant_distance_monotonic_for_valid_sequences(speeds):
    samples = [_sample(i * 0.2, v) for i, v in enumerate(speeds)]
    points = integrate_distance(samples)
    dists = [p.distance_m for p in points]
    assert dists == sorted(dists), f"distance decreased for speeds={speeds}"


@pytest.mark.parametrize("lap_length_m", [500.0, 1000.0, 4500.0])
def test_invariant_normalized_distance_in_unit_range_when_not_overshooting(lap_length_m):
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    samples = [_sample(t, 100.0) for t in range(11)]  # fixed, modest real-world distance
    trace = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE),
                           lap_length_m)
    for p in trace.points:
        if not p.is_overshoot:
            assert 0.0 <= p.normalized_distance <= 1.0


def test_invariant_repeated_execution_across_multiple_varied_inputs():
    for speeds in ([100] * 10, [0, 200, 50, 300], [360, 0, 360, 0, 360]):
        samples = [_sample(i, v) for i, v in enumerate(speeds)]
        r1 = integrate_distance(samples)
        r2 = integrate_distance(samples)
        assert [p.distance_m for p in r1] == [p.distance_m for p in r2]
        assert [p.confidence for p in r1] == [p.confidence for p in r2]


def test_repeated_execution_is_bit_for_bit_identical():
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, provenance=PROV)
    samples = [_sample(t * 0.37, 180.0 + (t % 5) * 12) for t in range(25)]

    trace1 = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE), 900.0)
    trace2 = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE), 900.0)

    assert [p.distance_m for p in trace1.points] == [p.distance_m for p in trace2.points]
    assert [p.normalized_distance for p in trace1.points] == \
           [p.normalized_distance for p in trace2.points]
    assert trace1.confidence == trace2.confidence
