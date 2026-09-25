"""Audit a real two-driver fixture against independent evidence.

Prints evidence; asserts nothing. The pass/fail gate is
backend/tests/test_real_pair_acceptance.py. This script reproduces the
numbers recorded in docs/PHASE_10_2_REAL_DATA_VALIDATION.md, so they can
be regenerated rather than taken on trust.

    cd backend
    python ../scripts/audit_real_pair.py [fixture_dir]

Sections:
  1. coverage and integrated distance vs the cited lap length
  2. official sector lines as fixed physical anchors: where each driver's
     integrated distance places them, and engine delta vs official split
  3. alignment sensitivity: ms of apparent delta per metre of A/B distance
     misalignment (= 1/speed) at chosen points
  4. segmentation fragmentation statistics
"""

from __future__ import annotations

import bisect
import json
import statistics
import sys
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

from app.analysis.delta_analysis import SegmentKind, analyze_delta
from app.analysis.lap_comparison import compare_driver_laps
from app.analysis.telemetry_integrity import telemetry_coverage
from app.providers.openf1.mapping import to_car_sample, to_lap

DEFAULT = Path(__file__).parent / "fixtures" / "real-openf1-pair"


def _dist_at_time(trace, t: float) -> float:
    ts = [p.ts.timestamp() for p in trace.points]
    i = min(max(bisect.bisect_right(ts, t), 1), len(ts) - 1)
    p0, p1 = trace.points[i - 1], trace.points[i]
    return p0.distance_m + (t - ts[i - 1]) / (ts[i] - ts[i - 1]) * (p1.distance_m - p0.distance_m)


def main(fixture: Path) -> None:
    meta = json.loads((fixture / "meta.json").read_text())
    sid, length = f"openf1:{meta['session_key']}", float(meta["lap_length_m"])
    ids = (meta["driver_a"], meta["driver_b"])
    laps, samples = {}, {}
    for d in ids:
        laps[d], _ = to_lap(json.loads((fixture / f"driver_{d}_lap.json").read_text()), sid)
        rows = json.loads((fixture / f"driver_{d}_car_data.json").read_text())
        samples[d] = sorted((to_car_sample(r, sid) for r in rows), key=lambda s: s.ts)
    a, b = ids
    cmp = compare_driver_laps(laps[a], samples[a], None, laps[b], samples[b], None,
                              lap_length_m=length)
    an = analyze_delta(cmp)
    traces = {a: cmp.trace_a, b: cmp.trace_b}

    print(f"session {meta['session_key']} {meta.get('year')} {meta.get('circuit_short_name')} "
          f"{meta.get('session_name')} | lap length {length} m ({meta['lap_length_source']})\n")
    print("1. coverage")
    for d in ids:
        c, lap = telemetry_coverage(samples[d]), laps[d]
        start_off = (c["first_ts"] - lap.started_at).total_seconds()
        end_off = lap.started_at.timestamp() + lap.duration_s - c["last_ts"].timestamp()
        tot = traces[d].total_distance_m
        print(f"  driver {d} lap {lap.lap_number}: {lap.duration_s:.3f}s official, {c['samples']} samples, "
              f"offsets start {start_off:.3f}s / end {end_off:.3f}s, largest gap {c['largest_gap_s']:.3f}s, "
              f"{tot:.1f} m integrated ({100 * (tot / length - 1):+.2f}%), "
              f"trace {traces[d].confidence.value}")

    print("\n2. official sector lines (fixed physical points)")
    cum = {a: 0.0, b: 0.0}
    for name, key in (("S1", "sector1_s"), ("S2", "sector2_s")):
        if getattr(laps[a], key) is None or getattr(laps[b], key) is None:
            print(f"  {name}: sector time missing - skipped")
            continue
        for d in ids:
            cum[d] += getattr(laps[d], key)
        pos = {d: _dist_at_time(traces[d], laps[d].started_at.timestamp() + cum[d]) for d in ids}
        x = round((pos[a] + pos[b]) / 2 / length, 3)
        engine = next((s.delta_t_s for s in an.samples if abs(s.x - x) < 1e-9), None)
        official = cum[a] - cum[b]
        err = f"{engine - official:+.3f}s" if engine is not None else "n/a"
        print(f"  {name}: located at {pos[a]:.1f} m / {pos[b]:.1f} m ({pos[a] - pos[b]:+.1f} m apart) | "
              f"official split delta {official:+.3f}s | engine {engine:+.3f}s | error {err}")
    offs = [(samples[d][0].ts - laps[d].started_at).total_seconds() for d in ids]
    print(f"  predicted start-offset bias (offA - offB): {offs[0] - offs[1]:+.3f}s")

    print("\n3. alignment sensitivity (ms of apparent delta per metre of misalignment)")
    for x in (0.10, 0.325, 0.40, 0.614, 0.69, 0.90):
        s = next((z for z in an.samples if abs(z.x - x) < 5e-4 and z.delta_t_s is not None), None)
        if s is None:
            continue
        v = (s.a["speed_kph"] + s.b["speed_kph"]) / 2 / 3.6
        print(f"  x={s.x:.3f}: delta {s.delta_t_s:+.3f}s at ~{v * 3.6:.0f} kph -> {1000 / v:.0f} ms/m")
    print(f"  max gain {an.max_gain_s:+.3f}s @ x={an.max_gain_x:.3f}; "
          f"max loss {an.max_loss_s:+.3f}s @ x={an.max_loss_x:.3f}")

    print("\n4. segmentation")
    segs = [g for g in an.segments if g.kind is not SegmentKind.NO_DATA]
    spans = [length * (g.x_end - g.x_start) for g in segs]
    print(f"  {len(segs)} segments (+{len(an.segments) - len(segs)} NO_DATA), median span "
          f"{statistics.median(spans):.1f} m, {sum(1 for s in spans if s < 50)} shorter than 50 m, "
          f"{sum(1 for g in segs if abs(g.time_change_s) < 0.010)} changing < 10 ms")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT)
