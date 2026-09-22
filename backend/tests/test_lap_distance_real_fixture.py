"""Phase 14: real OpenF1 data through the distance integration engine.

Uses tests/fixtures/real-openf1-9159 (see scripts/build_real_openf1_fixture.py)
- genuine car_data for 2023-09-15, session_key 9159, driver 55, not
synthetic. This dataset is honestly what it is: a real ~10-second
stationary engine-warmup sequence (speed=0 throughout - confirmed from the
raw fetch, not assumed) plus two real 315 km/h samples ~27 real minutes
apart. It is not a continuous flying lap; nothing here claims otherwise.
That shape happens to be a good real-world test of two different things
this engine must get right: a car that genuinely isn't moving must
integrate to genuinely zero distance, and a real ~27-minute discontinuity
must trigger real gap handling, not be silently smoothed over.

Expected values are computed from the fixture's own raw data in this
file, not hardcoded - per Phase 14's explicit requirement.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.analysis.common.models import Confidence
from app.analysis.lap_distance import MAX_GAP_S, integrate_distance
from app.core.enums import ProviderName
from app.providers.openf1.mapping import to_car_sample

FIXTURE_RAW = (Path(__file__).parent.parent.parent / "scripts" / "fixtures"
               / "real-openf1-9159" / "raw_car_data_source.json")
SESSION_ID = "openf1:9159"


def _load_real_rows() -> list[dict]:
    with open(FIXTURE_RAW) as f:
        rows = json.load(f)
    rows.sort(key=lambda r: r["date"])
    return rows


def test_real_data_maps_to_canonical_samples_via_the_real_mapper():
    """Provider -> mapping -> canonical, the same path live/replay data
    takes - not a hand-built model bypassing normalization."""
    rows = _load_real_rows()
    samples = [to_car_sample(row, SESSION_ID) for row in rows]

    assert len(samples) == len(rows)
    assert all(s.session_id == SESSION_ID for s in samples)
    assert all(s.provenance.provider == ProviderName.OPENF1 for s in samples)
    # the two real 315 km/h samples must survive mapping exactly
    high_speed = [s for s in samples if s.speed_kph == 315]
    assert len(high_speed) == 2
    assert {s.rpm for s in high_speed} == {11141, 11023}


def test_real_stationary_sequence_integrates_to_genuinely_zero_distance():
    """The real 12:48:06-12:48:16 cluster is a real engine warm-up with
    speed=0 throughout (confirmed directly from the raw fetch below, not
    assumed) - a car that is not moving must integrate to exactly zero
    distance. This is as important a real-data proof as a moving segment:
    it shows the engine doesn't fabricate motion that didn't happen."""
    rows = _load_real_rows()
    stationary_rows = [r for r in rows if r["date"].startswith("2023-09-15T12:48")]
    assert len(stationary_rows) == 37  # sanity: this is the real cluster size
    assert all(r["speed"] == 0 for r in stationary_rows), (
        "test assumption violated - the real data changed shape")

    samples = [to_car_sample(row, SESSION_ID) for row in stationary_rows]
    points = integrate_distance(samples)

    assert points[-1].distance_m == 0.0
    assert all(p.confidence == Confidence.HIGH for p in points)  # normal-rate real intervals


def test_real_27_minute_gap_triggers_real_gap_handling_not_smoothing():
    """The two real 315 km/h samples are ~27 real minutes apart (computed
    below from the actual fixture timestamps, not hardcoded). Feeding them
    straight through must produce a real, non-zero distance estimate for
    that interval, but flagged LOW confidence - the gap is genuinely huge
    relative to MAX_GAP_S, computed here, not assumed."""
    rows = _load_real_rows()
    high_speed_rows = [r for r in rows if r["speed"] == 315]
    assert len(high_speed_rows) == 2

    t0 = datetime.fromisoformat(high_speed_rows[0]["date"])
    t1 = datetime.fromisoformat(high_speed_rows[1]["date"])
    real_gap_s = (t1 - t0).total_seconds()
    assert real_gap_s > MAX_GAP_S * 100, "expected a genuinely huge real gap here"

    samples = [to_car_sample(row, SESSION_ID) for row in high_speed_rows]
    points = integrate_distance(samples)

    # both real samples are 315 km/h -> constant-speed trapezoidal integration
    # over the real measured gap, computed the same way the engine does it
    expected_m = (315.0 / 3.6) * real_gap_s
    assert points[-1].distance_m == pytest.approx(expected_m, rel=1e-9)
    assert points[-1].confidence == Confidence.LOW  # real huge gap, not hidden as HIGH
    assert points[-1].gap_s == pytest.approx(real_gap_s)
