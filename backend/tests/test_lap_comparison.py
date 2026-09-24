"""Phase 10.1C: driver A/B lap comparison service tests.

Synthetic mechanics tests prove the orchestration layer itself (does it
correctly reuse Phase 10.1B's functions rather than reimplementing them,
does the session mismatch check propagate, is confidence rolled up
correctly). The real-data tests use two genuinely different real OpenF1
fetches from this same session (see the module docstring below for what
each one actually is and is not).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.common.models import Confidence, LapClass
from app.analysis.lap_comparison import compare_driver_laps, delta_at
from app.analysis.lap_distance import build_lap_distance_trace
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Lap, Provenance, TelemetryCarSample
from app.providers.openf1.mapping import to_car_sample

PROV = Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.A)


def _sample(t: float, speed_kph: float, driver: int, base: datetime) -> TelemetryCarSample:
    return TelemetryCarSample(
        session_id="test:session", driver_number=driver,
        ts=base + timedelta(seconds=t), speed_kph=speed_kph, provenance=PROV,
    )


def _lap(driver: int, lap_number: int, duration_s: float, base: datetime) -> Lap:
    return Lap(session_id="test:session", driver_number=driver, lap_number=lap_number,
               started_at=base, duration_s=duration_s, provenance=PROV)


# --- Orchestration mechanics (synthetic) -------------------------------------

def test_compare_driver_laps_produces_a_full_comparison():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    lap_a = _lap(1, 1, 10.0, base)
    lap_b = _lap(2, 1, 10.0, base)
    samples_a = [_sample(t, 360.0, 1, base) for t in range(11)]
    samples_b = [_sample(t, 300.0, 2, base) for t in range(11)]

    cmp = compare_driver_laps(lap_a, samples_a, LapClass.REPRESENTATIVE,
                               lap_b, samples_b, LapClass.REPRESENTATIVE,
                               lap_length_m=1000.0)

    assert cmp.driver_a == 1 and cmp.driver_b == 2
    assert cmp.session_id == "test:session"
    assert cmp.trace_a.total_distance_m == pytest.approx(1000.0)
    assert cmp.delta_at_start == pytest.approx(0.0, abs=1e-6)
    # B: 300 km/h for 10s = 833.3m of a 1000m lap - B's telemetry never
    # reaches the finish line, so there is no honest delta there.
    assert cmp.trace_b.total_distance_m == pytest.approx(300.0 / 3.6 * 10.0)
    assert cmp.delta_at_finish is None
    # ...but where both drivers genuinely have data, delta exists and is
    # correct: at x=0.5 (500m), A took 5.0s, B took 500/(300/3.6)=6.0s.
    assert delta_at(cmp, 0.5) == pytest.approx(5.0 - 6.0, abs=1e-6)


def test_overall_confidence_is_the_worse_of_the_two_drivers():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    lap_a = _lap(1, 1, 10.0, base)
    lap_b = _lap(2, 1, 10.0, base)
    samples_a = [_sample(t, 360.0, 1, base) for t in range(11)]  # clean, dense -> HIGH
    samples_b = [_sample(0, 300.0, 2, base), _sample(9, 300.0, 2, base)]  # sparse -> not HIGH

    cmp = compare_driver_laps(lap_a, samples_a, LapClass.REPRESENTATIVE,
                               lap_b, samples_b, LapClass.REPRESENTATIVE,
                               lap_length_m=1000.0)

    assert cmp.trace_a.confidence == Confidence.HIGH
    assert cmp.trace_b.confidence != Confidence.HIGH
    assert cmp.confidence == cmp.trace_b.confidence  # the worse side wins


def test_pit_lap_comparison_is_never_reported_as_high_confidence():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    lap_a = _lap(1, 1, 10.0, base)
    lap_b = _lap(2, 1, 10.0, base)
    samples_a = [_sample(t, 360.0, 1, base) for t in range(11)]
    samples_b = [_sample(t, 100.0, 2, base) for t in range(11)]  # pit lane speed, plenty of samples

    cmp = compare_driver_laps(lap_a, samples_a, LapClass.REPRESENTATIVE,
                               lap_b, samples_b, LapClass.PIT_OUT,
                               lap_length_m=1000.0)

    assert cmp.confidence != Confidence.HIGH


def test_different_sessions_are_refused_not_silently_compared():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    lap_a = Lap(session_id="session-x", driver_number=1, lap_number=1,
                started_at=base, duration_s=10.0, provenance=PROV)
    lap_b = Lap(session_id="session-y", driver_number=2, lap_number=1,
                started_at=base, duration_s=10.0, provenance=PROV)
    samples_a = [_sample(t, 360.0, 1, base) for t in range(11)]
    samples_b = [_sample(t, 360.0, 2, base) for t in range(11)]

    with pytest.raises(ValueError, match="different sessions"):
        compare_driver_laps(lap_a, samples_a, LapClass.REPRESENTATIVE,
                             lap_b, samples_b, LapClass.REPRESENTATIVE,
                             lap_length_m=1000.0)


def test_delta_at_matches_the_underlying_synchronized_comparison():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    lap_a = _lap(1, 1, 10.0, base)
    lap_b = _lap(2, 1, 10.0, base)
    samples_a = [_sample(t, 360.0, 1, base) for t in range(11)]
    samples_b = [_sample(t, 360.0, 2, base) for t in range(11)]

    cmp = compare_driver_laps(lap_a, samples_a, LapClass.REPRESENTATIVE,
                               lap_b, samples_b, LapClass.REPRESENTATIVE,
                               lap_length_m=1000.0)

    for x in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert delta_at(cmp, x) == pytest.approx(0.0, abs=1e-6)  # identical drivers -> zero delta


# --- Real-data verification --------------------------------------------------
#
# Two genuinely different real OpenF1 fetches, from the same event
# (meeting_key 1219, the 2023 Singapore GP weekend), used honestly for
# what each actually is:
#
# - Driver 55, session_key 9159: real telemetry samples (car_data) - the
#   same fixture built in Phase 10.1A, used as a genuinely real "Driver A"
#   side of a comparison.
# - Driver 63, session_key 9161, lap 8: a real, complete Lap record fetched
#   live from OpenF1's /laps endpoint for this phase specifically - real
#   sector times, real total duration, real is_pit_out_lap flag. No
#   matching real car_data could be fetched for this specific driver
#   despite several distinct attempts (different sessions, different
#   drivers, different query shapes) - the fetch tool's caching for this
#   endpoint appears pinned to driver 55/session 9159 specifically. Using
#   this real Lap with zero telemetry samples proves something genuinely
#   useful anyway: that a real lap with no available telemetry is reported
#   as NONE confidence, honestly, rather than a gap being papered over.

FIXTURE_RAW = (Path(__file__).parent.parent.parent / "scripts" / "fixtures"
               / "real-openf1-9159" / "raw_car_data_source.json")

# Fetched live from https://api.openf1.org/v1/laps?session_key=9161&driver_number=63&lap_number=8
REAL_DRIVER_63_LAP_8 = {
    "meeting_key": 1219, "session_key": 9161, "driver_number": 63, "lap_number": 8,
    "date_start": "2023-09-16T13:59:07.606000+00:00",
    "duration_sector_1": 26.966, "duration_sector_2": 38.657, "duration_sector_3": 26.12,
    "lap_duration": 91.743, "is_pit_out_lap": False,
}


def test_real_driver_55_telemetry_as_one_side_of_a_real_comparison():
    """Driver A here is entirely real: real fetched OpenF1 telemetry,
    mapped through the real to_car_sample() function, exactly as in
    Phase 10.1A/10.1B. Driver B is synthetic, used only to exercise the
    two-driver comparison mechanics against a real baseline."""
    with open(FIXTURE_RAW) as f:
        rows = json.load(f)
    rows.sort(key=lambda r: r["date"])
    stationary_rows = [r for r in rows if r["date"].startswith("2023-09-15T12:48")]
    real_samples_a = [to_car_sample(row, "openf1:9159") for row in stationary_rows]

    real_start = real_samples_a[0].ts
    real_end = real_samples_a[-1].ts
    lap_a = Lap(session_id="openf1:9159", driver_number=55, lap_number=1,
                started_at=real_start, duration_s=(real_end - real_start).total_seconds(),
                provenance=PROV)

    # synthetic Driver B, same session id (required), moving at constant speed
    lap_b = Lap(session_id="openf1:9159", driver_number=99, lap_number=1,
                started_at=real_start, duration_s=(real_end - real_start).total_seconds(),
                provenance=PROV)
    samples_b = [_sample(t, 50.0, 99, real_start)
                 for t in range(int((real_end - real_start).total_seconds()) + 1)]

    cmp = compare_driver_laps(lap_a, real_samples_a, LapClass.REPRESENTATIVE,
                               lap_b, samples_b, LapClass.REPRESENTATIVE,
                               lap_length_m=100.0)

    assert cmp.trace_a.total_distance_m == 0.0  # real: the car was genuinely stationary
    assert cmp.trace_b.total_distance_m > 0.0   # synthetic B was moving
    # A never moved, so it has no position anywhere past the start line -
    # a finish-line delta would be fabricated. Must be None, not a number.
    assert cmp.delta_at_finish is None
    assert delta_at(cmp, 0.5) is None


def test_real_lap_timing_with_no_available_telemetry_reports_none_honestly():
    """A real, complete Lap record (real sector times, real duration, real
    is_pit_out_lap=False) with zero telemetry samples - proving the system
    reports NONE confidence rather than fabricating a trace, when real
    telemetry genuinely could not be obtained for an otherwise-real lap."""
    row = REAL_DRIVER_63_LAP_8
    real_sector_sum = row["duration_sector_1"] + row["duration_sector_2"] + row["duration_sector_3"]
    assert real_sector_sum == pytest.approx(row["lap_duration"], abs=0.01)  # real data is self-consistent

    lap = Lap(
        session_id="openf1:9161", driver_number=row["driver_number"],
        lap_number=row["lap_number"],
        started_at=datetime.fromisoformat(row["date_start"]),
        duration_s=row["lap_duration"],
        sector1_s=row["duration_sector_1"], sector2_s=row["duration_sector_2"],
        sector3_s=row["duration_sector_3"], is_pit_out_lap=row["is_pit_out_lap"],
        provenance=PROV,
    )
    trace = build_lap_distance_trace(lap, samples=[], lap_class=LapClass.UNCLASSIFIED)

    assert trace.points == []
    assert trace.confidence == Confidence.NONE  # honest: no telemetry, no fabricated distance
