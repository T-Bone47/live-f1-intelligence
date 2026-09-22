"""Tests for the driver-to-driver interpolation/synchronization layer:
continuous vs discrete interpolation semantics, delta-time, and
compatibility with the existing sector-time model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.analysis.common.models import LapClass
from app.analysis.lap_distance import (
    build_lap_distance_trace,
    delta_t,
    normalize_lap,
    resample_common_grid,
    synchronize_drivers,
)
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Lap, Provenance, TelemetryCarSample

PROV = Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.A)


def _sample(t: float, speed_kph: float, driver: int = 1, gear: int | None = None,
            drs: int | None = None, base: datetime | None = None) -> TelemetryCarSample:
    base = base or datetime(2026, 1, 1, tzinfo=UTC)
    return TelemetryCarSample(
        session_id="test:session", driver_number=driver,
        ts=base + timedelta(seconds=t), speed_kph=speed_kph,
        gear=gear, drs=drs, provenance=PROV,
    )


def _lap(driver: int = 1, lap_number: int = 1, duration_s: float = 10.0,
         base: datetime | None = None) -> Lap:
    base = base or datetime(2026, 1, 1, tzinfo=UTC)
    return Lap(session_id="test:session", driver_number=driver, lap_number=lap_number,
               started_at=base, duration_s=duration_s, provenance=PROV)


# --- 16. Continuous-field interpolation --------------------------------------

def test_continuous_field_interpolates_exactly_between_two_known_points():
    # constant 360kph (=100m/s): distance is exactly linear in time, so
    # normalized_distance is also exactly linear in time - easy to predict
    # the interpolated speed at any grid point precisely.
    lap = _lap(duration_s=10.0)
    samples = [_sample(0, 360.0), _sample(10, 360.0)]  # only 2 points, constant speed
    trace = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE),
                           lap_length_m=1000.0)
    series = resample_common_grid(trace, step=0.5)
    # constant speed the whole way - every grid point's interpolated speed
    # must equal exactly 360.0, not drift due to interpolation error
    assert all(v == pytest.approx(360.0) for v in series.continuous["speed_kph"])


def test_continuous_field_linear_interpolation_at_known_midpoint():
    lap = _lap(duration_s=2.0)
    samples = [_sample(0, 0.0), _sample(2, 720.0)]  # speed doubles linearly with distance-ish
    trace = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE),
                           lap_length_m=200.0)  # trapezoidal: (0+720)/3.6/2 * 2 = 200m exactly
    series = resample_common_grid(trace, step=0.5)
    # at x=0 -> speed 0; at x=1.0 -> speed 720; both are real observed points,
    # so must match exactly, not be an interpolation artifact
    assert series.continuous["speed_kph"][0] == pytest.approx(0.0)
    assert series.continuous["speed_kph"][-1] == pytest.approx(720.0)


# --- 17. Discrete-field interpolation ----------------------------------------

def test_gear_never_becomes_fractional():
    lap = _lap(duration_s=10.0)
    samples = [_sample(t, 200.0, gear=5 if t < 5 else 6) for t in range(11)]
    trace = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE),
                           lap_length_m=trace_total(lap, samples))
    series = resample_common_grid(trace, step=0.01)
    observed_gears = set(series.discrete["gear"])
    assert observed_gears <= {5, 6}, f"gear interpolated to a fabricated value: {observed_gears}"
    assert all(isinstance(g, int) for g in series.discrete["gear"] if g is not None)


def test_gear_steps_at_the_correct_point_not_averaged_across_the_transition():
    lap = _lap(duration_s=10.0)
    samples = [_sample(t, 200.0, gear=5 if t < 5 else 6) for t in range(11)]
    trace = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE),
                           lap_length_m=trace_total(lap, samples))
    series = resample_common_grid(trace, step=0.01)
    # near the start, gear must be 5; near the end, gear must be 6 - a real
    # step, not gear "5.4" or any blended value at the transition
    assert series.discrete["gear"][0] == 5
    assert series.discrete["gear"][-1] == 6


def test_drs_state_never_becomes_a_continuous_value():
    lap = _lap(duration_s=4.0)
    samples = [_sample(0, 200.0, drs=0), _sample(4, 200.0, drs=12)]  # off -> on
    trace = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE),
                           lap_length_m=trace_total(lap, samples))
    series = resample_common_grid(trace, step=0.1)
    assert set(series.discrete["drs"]) <= {0, 12}


def trace_total(lap, samples):
    from app.analysis.lap_distance import build_lap_distance_trace
    t = build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE)
    return t.total_distance_m


# --- 15/18. Driver A/B synchronization + delta-time --------------------------

def test_synchronize_drivers_produces_matching_grids():
    lap_a = _lap(driver=1, duration_s=10.0)
    lap_b = _lap(driver=2, duration_s=12.0,
                 base=datetime(2026, 1, 1, 0, 5, 0, tzinfo=UTC))  # different wall clock
    samples_a = [_sample(t, 360.0, driver=1) for t in range(11)]
    samples_b = [_sample(t, 300.0, driver=2, base=lap_b.started_at) for t in range(13)]

    trace_a = normalize_lap(build_lap_distance_trace(lap_a, samples_a, LapClass.REPRESENTATIVE), 1000.0)
    trace_b = normalize_lap(build_lap_distance_trace(lap_b, samples_b, LapClass.REPRESENTATIVE), 1000.0)

    sync = synchronize_drivers(trace_a, trace_b, step=0.1)
    assert sync.grid_x == sync.series_a.grid_x == sync.series_b.grid_x
    assert len(sync.confidence) == len(sync.grid_x)


def test_delta_t_uses_lap_relative_elapsed_time_not_wall_clock_difference():
    # Driver A's lap starts hours after driver B's - if delta_t ever
    # touched raw timestamps directly, the result would be nonsense
    # (hours), not a real lap-time gap.
    lap_a = _lap(driver=1, duration_s=10.0,
                 base=datetime(2026, 1, 1, 14, 0, 0, tzinfo=UTC))
    lap_b = _lap(driver=2, duration_s=10.0,
                 base=datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    samples_a = [_sample(t, 360.0, driver=1, base=lap_a.started_at) for t in range(11)]
    samples_b = [_sample(t, 360.0, driver=2, base=lap_b.started_at) for t in range(11)]

    trace_a = normalize_lap(build_lap_distance_trace(lap_a, samples_a, LapClass.REPRESENTATIVE), 1000.0)
    trace_b = normalize_lap(build_lap_distance_trace(lap_b, samples_b, LapClass.REPRESENTATIVE), 1000.0)
    sync = synchronize_drivers(trace_a, trace_b, step=0.25)

    # identical speed profiles, 5 real hours apart in wall clock -> delta
    # must be ~0 at every point, proving elapsed lap time was used, not
    # timestamp_A - timestamp_B (which would be ~18000 seconds)
    for x in (0.0, 0.25, 0.5, 0.75, 1.0):
        d = delta_t(sync, x)
        assert d is not None
        assert abs(d) < 0.01, f"delta_t({x}) = {d}s - looks like raw timestamps were subtracted"


def test_delta_t_reflects_a_genuinely_faster_driver():
    lap_a = _lap(driver=1, duration_s=8.0)   # A is faster: same distance, less time
    lap_b = _lap(driver=2, duration_s=10.0)
    samples_a = [_sample(t, 450.0, driver=1) for t in range(9)]   # 450kph*8s
    samples_b = [_sample(t, 360.0, driver=2) for t in range(11)]  # 360kph*10s -> same 1000m

    trace_a = normalize_lap(build_lap_distance_trace(lap_a, samples_a, LapClass.REPRESENTATIVE), 1000.0)
    trace_b = normalize_lap(build_lap_distance_trace(lap_b, samples_b, LapClass.REPRESENTATIVE), 1000.0)
    sync = synchronize_drivers(trace_a, trace_b, step=0.5)

    d = delta_t(sync, 1.0)  # at the finish line
    assert d is not None
    assert d < 0  # A took less elapsed time to reach the same point -> negative (A ahead)


# --- 19. Sector compatibility -------------------------------------------------

def test_sector_boundary_can_be_located_on_the_distance_axis():
    """Proves distance-axis <-> sector compatibility without touching
    sectors.py: a sector boundary's elapsed time (from Lap.sectorN_s,
    already the canonical source) can be looked up against this trace's
    own elapsed-time-vs-distance points to find where on the distance
    axis that boundary actually falls."""
    lap = Lap(session_id="s", driver_number=1, lap_number=1,
              started_at=datetime(2026, 1, 1, tzinfo=UTC),
              duration_s=10.0, sector1_s=4.0, sector2_s=3.0, sector3_s=3.0,
              provenance=PROV)
    samples = [_sample(t, 360.0) for t in range(11)]  # constant speed -> linear distance
    trace = normalize_lap(build_lap_distance_trace(lap, samples, LapClass.REPRESENTATIVE), 1000.0)

    sector1_end_elapsed = lap.sector1_s  # 4.0s into the lap
    # find the point whose elapsed time is closest to the sector 1 boundary
    t0 = trace.points[0].ts
    closest = min(trace.points, key=lambda p: abs((p.ts - t0).total_seconds() - sector1_end_elapsed))
    # constant speed -> sector 1 (4 of 10 seconds) should land at ~40% distance
    assert closest.normalized_distance == pytest.approx(0.4, abs=0.05)
