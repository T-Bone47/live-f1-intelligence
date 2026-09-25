"""Phase 10.3 real-data gate: position alignment on the real Singapore pair.

Needs driver_<n>_location.json in the real fixture (fetched by
scripts/fetch_real_driver_pair.py v2). SKIPS without it - never synthetic.

The central claim is falsifiable. Official sector lines are fixed physical
points. Speed integration placed them 4.3 m (S1) and 2.0 m (S2) apart
between the two drivers (docs/PHASE_10_2_REAL_DATA_VALIDATION.md). If
projecting both drivers onto the pole lap's own path does not place them
closer, the test fails - and that is the answer we want to know.
"""

from __future__ import annotations

import bisect
import json
import os
from pathlib import Path

import pytest

from app.analysis.common.models import Confidence
from app.analysis.delta_analysis import SegmentKind, analyze_delta
from app.analysis.lap_comparison import compare_traces
from app.analysis.lap_distance import build_lap_distance_trace
from app.analysis.track_geometry import (
    OFFSET_TOL_FRACTION,
    build_centerline,
    build_position_distance_trace,
    project_positions,
)
from app.providers.openf1.mapping import to_car_sample, to_lap, to_location_sample
from app.providers.openf1.real_data import validate_rows_identity

FIXTURE_DIR = Path(os.environ.get(
    "REAL_PAIR_FIXTURE_DIR",
    Path(__file__).parent.parent.parent / "scripts" / "fixtures" / "real-openf1-pair"))


def _has_location() -> bool:
    if not (FIXTURE_DIR / "meta.json").exists():
        return False
    meta = json.loads((FIXTURE_DIR / "meta.json").read_text())
    return all((FIXTURE_DIR / f"driver_{d}_location.json").exists()
               for d in (meta["driver_a"], meta["driver_b"]))


pytestmark = pytest.mark.skipif(
    not _has_location(),
    reason="real fixture has no location data - re-run scripts/fetch_real_driver_pair.py (v2)")


@pytest.fixture(scope="module")
def real():
    meta = json.loads((FIXTURE_DIR / "meta.json").read_text())
    sid, length = f"openf1:{meta['session_key']}", float(meta["lap_length_m"])
    side = {}
    for d in (meta["driver_a"], meta["driver_b"]):
        lap, _ = to_lap(json.loads((FIXTURE_DIR / f"driver_{d}_lap.json").read_text()), sid)
        car_rows = json.loads((FIXTURE_DIR / f"driver_{d}_car_data.json").read_text())
        loc_rows = json.loads((FIXTURE_DIR / f"driver_{d}_location.json").read_text())
        side[d] = {
            "lap": lap, "loc_rows": loc_rows,
            "car": sorted((to_car_sample(r, sid) for r in car_rows), key=lambda s: s.ts),
            "loc": sorted((to_location_sample(r, sid) for r in loc_rows), key=lambda s: s.ts),
        }
    a, b = meta["driver_a"], meta["driver_b"]
    # Reference path: driver A's own lap (the pole lap in the committed fixture).
    t0 = side[a]["lap"].started_at.timestamp()
    ref = [s for s in side[a]["loc"]
           if t0 <= s.ts.timestamp() <= t0 + side[a]["lap"].duration_s]
    cl = build_centerline(ref)
    pos = {d: build_position_distance_trace(side[d]["lap"], side[d]["car"], side[d]["loc"],
                                            cl, length) for d in (a, b)}
    spd = {d: build_lap_distance_trace(side[d]["lap"], side[d]["car"]) for d in (a, b)}
    return meta, length, side, cl, pos, spd


def _dist_at_time(trace, t: float) -> float:
    ts = [p.ts.timestamp() for p in trace.points]
    i = min(max(bisect.bisect_right(ts, t), 1), len(ts) - 1)
    p0, p1 = trace.points[i - 1], trace.points[i]
    return p0.distance_m + (t - ts[i - 1]) / (ts[i] - ts[i - 1]) * (p1.distance_m - p0.distance_m)


def test_location_identity(real):
    meta, _l, side, *_ = real
    for d, s in side.items():
        validate_rows_identity(s["loc_rows"], driver_number=d, session_key=meta["session_key"])


def test_both_drivers_share_the_reference_frame(real):
    """Driver B projected onto driver A's path stays close to it. If the two
    feeds were not in one frame, offsets would be large and most points
    rejected."""
    meta, _l, side, cl, pos, _s = real
    b = meta["driver_b"]
    lap = side[b]["lap"]
    t0 = lap.started_at.timestamp()
    in_lap = [s for s in side[b]["loc"] if t0 <= s.ts.timestamp() <= t0 + lap.duration_s]
    proj = project_positions(cl, in_lap, lap.duration_s)
    offsets = sorted(p.offset for p in proj)
    assert offsets[len(offsets) // 2] < OFFSET_TOL_FRACTION * cl.total_length
    rejected = sum(1 for p in proj if p.confidence is Confidence.NONE)
    assert rejected / len(proj) < 0.05, f"{rejected}/{len(proj)} positions rejected"
    for d in pos:
        assert pos[d].is_complete and pos[d].confidence is not Confidence.NONE


@pytest.mark.parametrize("line", ["sector1_s", "sector2_s"])
def test_position_places_official_sector_lines_closer_than_speed(real, line):
    meta, _l, side, _cl, pos, spd = real
    a, b = meta["driver_a"], meta["driver_b"]
    keys = ["sector1_s"] if line == "sector1_s" else ["sector1_s", "sector2_s"]
    t = {d: side[d]["lap"].started_at.timestamp() + sum(getattr(side[d]["lap"], k) for k in keys)
         for d in (a, b)}
    mismatch_pos = abs(_dist_at_time(pos[a], t[a]) - _dist_at_time(pos[b], t[b]))
    mismatch_spd = abs(_dist_at_time(spd[a], t[a]) - _dist_at_time(spd[b], t[b]))
    assert mismatch_pos < mismatch_spd, (
        f"{line}: position {mismatch_pos:.2f} m vs speed {mismatch_spd:.2f} m apart")


def test_position_comparison_never_fabricates(real):
    meta, length, _side, _cl, pos, _s = real
    cmp = compare_traces(pos[meta["driver_a"]], pos[meta["driver_b"]], lap_length_m=length)
    an = analyze_delta(cmp)
    for trace in (cmp.trace_a, cmp.trace_b):
        d = [p.distance_m for p in trace.points]
        assert d == sorted(d)                                   # never runs backwards
        assert trace.time_origin is not None
    for seg in an.segments:
        region = an.samples[seg.start_index:seg.end_index + 1]
        if seg.kind is not SegmentKind.NO_DATA:
            assert all(s.delta_t_s is not None for s in region)
