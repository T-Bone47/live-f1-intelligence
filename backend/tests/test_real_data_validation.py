"""Phase 10.2 real-data validation: identity guard, lap selection, and
telemetry integrity checks.

The identity-guard tests encode a failure actually observed in this
project: a tool-level cache served driver 55 / session 9159 car_data in
response to requests for other drivers and sessions. Nothing in the OpenF1
layer compared what was requested against what came back.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest

from app.analysis.telemetry_integrity import telemetry_coverage
from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Provenance, TelemetryCarSample
from app.providers.openf1.mapping import to_car_sample
from app.providers.openf1.real_data import (
    IdentityMismatch,
    select_reference_lap,
    validate_rows_identity,
)

PROV = Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.B)
REAL_RAW = (Path(__file__).parent.parent.parent / "scripts" / "fixtures"
            / "real-openf1-9159" / "raw_car_data_source.json")


# --- Section 3: identity guard ----------------------------------------------

def test_guard_rejects_the_observed_cross_driver_cache_contamination():
    """Requested driver 1 / session 11353; the cache served real driver-55,
    session-9159 rows. This must fail loudly, not be accepted."""
    served = json.loads(REAL_RAW.read_text())
    with pytest.raises(IdentityMismatch, match="driver_number"):
        validate_rows_identity(served, driver_number=1, session_key=11353)


def test_guard_rejects_right_driver_wrong_session():
    served = json.loads(REAL_RAW.read_text())
    with pytest.raises(IdentityMismatch, match="session_key"):
        validate_rows_identity(served, driver_number=55, session_key=11353)


def test_guard_rejects_a_single_contaminating_row_among_correct_ones():
    served = json.loads(REAL_RAW.read_text())
    mixed = [*served, {**served[0], "driver_number": 44}]
    with pytest.raises(IdentityMismatch):
        validate_rows_identity(mixed, driver_number=55, session_key=9159)


def test_guard_rejects_rows_missing_identity_fields():
    with pytest.raises(IdentityMismatch):
        validate_rows_identity([{"speed": 300}], driver_number=55, session_key=9159)


def test_guard_accepts_genuinely_matching_real_rows():
    served = json.loads(REAL_RAW.read_text())
    assert validate_rows_identity(served, driver_number=55, session_key=9159) == len(served)


def test_guard_accepts_string_or_int_request_values():
    served = json.loads(REAL_RAW.read_text())
    assert validate_rows_identity(served, driver_number="55", session_key="9159") == len(served)


# --- Lap selection rule --------------------------------------------------------

def _lap(n, dur, pit_out=False):
    return {"driver_number": 63, "session_key": 9161, "lap_number": n,
            "date_start": "2023-09-16T13:59:07.606000+00:00",
            "lap_duration": dur, "is_pit_out_lap": pit_out}


def test_selection_picks_fastest_complete_non_pit_out_lap():
    laps = [_lap(1, None, pit_out=True), _lap(2, 95.1), _lap(3, 91.743),
            _lap(4, 90.0, pit_out=True), _lap(5, None)]
    assert select_reference_lap(laps)["lap_number"] == 3


def test_selection_honours_an_explicit_lap_number():
    laps = [_lap(2, 95.1), _lap(3, 91.743)]
    assert select_reference_lap(laps, lap_number=2)["lap_number"] == 2


def test_selection_refuses_an_explicit_pit_out_or_incomplete_lap():
    laps = [_lap(4, 90.0, pit_out=True), _lap(5, None)]
    with pytest.raises(ValueError):
        select_reference_lap(laps, lap_number=4)
    with pytest.raises(ValueError):
        select_reference_lap(laps, lap_number=5)


def test_selection_returns_none_when_no_eligible_lap_exists():
    assert select_reference_lap([_lap(1, None, pit_out=True)]) is None


# --- Section 6: integrity / coverage -----------------------------------------

def test_coverage_of_the_real_fixture_matches_independent_computation():
    rows = sorted(json.loads(REAL_RAW.read_text()), key=lambda r: r["date"])
    samples = [to_car_sample(r, "openf1:9159") for r in rows]
    cov = telemetry_coverage(samples)

    tss = [datetime.fromisoformat(r["date"]) for r in rows]
    gaps = [(b - a).total_seconds() for a, b in pairwise(tss)]
    assert cov["samples"] == len(rows) == 39
    assert cov["first_ts"] == tss[0] and cov["last_ts"] == tss[-1]
    assert cov["duration_s"] == pytest.approx((tss[-1] - tss[0]).total_seconds())
    assert cov["largest_gap_s"] == pytest.approx(max(gaps))
    assert cov["gaps_above_threshold"] == 2          # the two real multi-minute gaps
    assert cov["monotonic"] is True
    assert cov["duplicate_timestamps"] == 0
    assert cov["speed_valid_pct"] == pytest.approx(100.0)
    assert cov["speed_min_kph"] == 0 and cov["speed_max_kph"] == 315
    assert cov["zero_speed_samples"] == 37            # the stationary warm-up
    for f in ("throttle_pct", "brake_pct", "rpm", "gear", "drs"):
        assert cov["field_available_pct"][f] == pytest.approx(100.0)


def test_coverage_reports_regressions_duplicates_and_missing_fields():
    base = datetime(2026, 1, 1, tzinfo=UTC)

    def s(t, speed):
        return TelemetryCarSample(session_id="s", driver_number=1,
                                  ts=base + timedelta(seconds=t), speed_kph=speed,
                                  provenance=PROV)

    cov = telemetry_coverage([s(0, 100), s(1, None), s(1, 120), s(0.5, 130)])
    assert cov["monotonic"] is False
    assert cov["duplicate_timestamps"] == 1
    assert cov["speed_valid_pct"] == pytest.approx(75.0)
    assert cov["field_available_pct"]["throttle_pct"] == pytest.approx(0.0)


def test_coverage_of_empty_input_is_explicit_not_an_error():
    cov = telemetry_coverage([])
    assert cov["samples"] == 0
    assert cov["first_ts"] is None and cov["largest_gap_s"] is None
