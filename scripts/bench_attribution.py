"""Phase 10.4 attribution benchmark: wall time, throughput, peak memory.

    cd backend
    python ../scripts/bench_attribution.py

Times attribute_comparison ONLY (10.1B/10.1C/10.2 are built once, outside
the timer). Cases: the real Singapore pair at the default grid (0.001) and
at a 10x finer grid, plus a SYNTHETIC 10x longer lap (timing only - never
evidence) to check scaling with the number of real samples.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

from app.analysis.attribution import attribute_comparison
from app.analysis.delta_analysis import analyze_delta
from app.analysis.lap_comparison import compare_driver_laps
from app.providers.openf1.mapping import to_car_sample, to_lap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "tests"))
from synthetic_lap import Profile, make_lap

RUNS = 15


def _real(step: float):
    fx = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
    meta = json.loads((fx / "meta.json").read_text())
    sid = f"openf1:{meta['session_key']}"
    laps, samples = {}, {}
    for d in (meta["driver_a"], meta["driver_b"]):
        laps[d], _ = to_lap(json.loads((fx / f"driver_{d}_lap.json").read_text()), sid)
        rows = json.loads((fx / f"driver_{d}_car_data.json").read_text())
        samples[d] = sorted((to_car_sample(r, sid) for r in rows), key=lambda s: s.ts)
    a, b = meta["driver_a"], meta["driver_b"]
    cmp = compare_driver_laps(laps[a], samples[a], None, laps[b], samples[b], None,
                              lap_length_m=meta["lap_length_m"], step=step)
    return analyze_delta(cmp), laps[a], laps[b], len(samples[a]) + len(samples[b])


def _long_synthetic(step: float, corners: int = 20):
    speed, brake, thr, gear = [(0.0, 280)], [], [(0.0, 100)], [(0.0, 8)]
    s = 0.0
    for _ in range(corners):
        speed += [(s + 700, 300), (s + 800, 110), (s + 850, 110), (s + 1000, 290)]
        brake.append((s + 700, s + 800))
        thr += [(s + 695, 100), (s + 700, 0), (s + 820, 0), (s + 900, 100)]
        gear += [(s + 720, 5), (s + 780, 3), (s + 880, 5), (s + 950, 8)]
        s += 1000
    prof = Profile(length_m=s, speed_knots=speed + [(s, 290)], brake=brake,
                   throttle_knots=thr + [(s, 100)], gear_knots=gear,
                   sector_lines_m=(s / 3, 2 * s / 3))
    late = Profile(**{**prof.__dict__, "brake": [(a + 15, b) for a, b in brake]})
    la, sa = make_lap(prof, 1)
    lb, sb = make_lap(late, 2, phase_s=0.1)
    cmp = compare_driver_laps(la, sa, None, lb, sb, None, lap_length_m=s, step=step)
    return analyze_delta(cmp), la, lb, len(sa) + len(sb)


def _bench(label, built):
    an, la, lb, n_samples = built
    times = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        report = attribute_comparison(an, la, lb)
        times.append(time.perf_counter() - t0)
    tracemalloc.start()
    attribute_comparison(an, la, lb)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    med = statistics.median(times)
    grid = len(an.samples)
    print(f"{label:<34} grid {grid:>6}  samples {n_samples:>5}  segments "
          f"{len(report.segments):>3}  median {med * 1000:7.2f} ms  "
          f"{grid / med / 1000:7.1f} k grid-pts/s  peak {peak / 1024:7.0f} KiB")
    return med


def main() -> None:
    print(f"attribute_comparison only; median of {RUNS} runs; Python {sys.version.split()[0]}")
    r1 = _bench("REAL Singapore pair, step 0.001", _real(0.001))
    r2 = _bench("REAL Singapore pair, step 0.0001", _real(0.0001))
    s1 = _bench("SYNTHETIC 20 km lap, step 0.001", _long_synthetic(0.001))
    s2 = _bench("SYNTHETIC 20 km lap, step 0.0001", _long_synthetic(0.0001))
    print(f"scaling: 10x grid -> {r2 / r1:.1f}x time (real), {s2 / s1:.1f}x (synthetic)")


if __name__ == "__main__":
    main()
