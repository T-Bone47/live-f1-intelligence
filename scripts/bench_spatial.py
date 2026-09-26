"""Phase 12A performance, measured on the real recording (never claimed).

    cd backend
    python ../scripts/bench_spatial.py

Measures: the cold build (load + build + serialize + index write, the
store's miss path), the warm cache load (a fresh store reading the caches next
to the recording), spatial_state_v1 latency over 1,000 seeded-random times
inside the race (document build + contract validation + canonical bytes, i.e.
the /spatial route minus HTTP), and the tracemalloc peak of loading the index.
"""

from __future__ import annotations

import random
import statistics
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)
from spatial_report import SID, find_recording

from app.analysis.timeline import to_canonical_json
from app.spatial.builder import build_spatial, state_doc
from app.spatial.source import load_inputs
from app.storage.spatial_store import INDEX_CACHE, SpatialStore, read_index, write_index


def main() -> int:
    rec = find_recording()
    if rec is None:
        print("no recording")
        return 2
    t0 = time.perf_counter()
    inputs = load_inputs(rec, SID)
    t1 = time.perf_counter()
    doc, index = build_spatial(inputs)
    t2 = time.perf_counter()
    to_canonical_json(doc)
    with tempfile.TemporaryDirectory() as tmp:
        write_index(Path(tmp) / INDEX_CACHE, index)
        size = (Path(tmp) / INDEX_CACHE).stat().st_size
    t3 = time.perf_counter()
    print(f"cold build: load {t1 - t0:.1f} s + build {t2 - t1:.1f} s + write {t3 - t2:.2f} s "
          f"= {t3 - t0:.1f} s; index {size / 1e6:.1f} MB")

    store = SpatialStore(rec.parent)
    store.get_track(SID)                     # make sure the caches exist and match
    w0 = time.perf_counter()
    fresh = SpatialStore(rec.parent)
    fresh.get_index(SID)
    w1 = time.perf_counter()
    print(f"warm cache load (fresh store, caches on disk): {w1 - w0:.2f} s")

    tracemalloc.start()
    read_index(rec / INDEX_CACHE)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"read_index tracemalloc peak: {peak / 1e6:.1f} MB")

    starts = [r.start for rows in inputs.laps.values() for r in rows]
    ends = [r.start + r.duration for rows in inputs.laps.values() for r in rows if r.duration]
    rng = random.Random(42)
    times = []
    for _ in range(1000):
        at = datetime.fromtimestamp(rng.uniform(min(starts), max(ends)), UTC)
        q0 = time.perf_counter()
        to_canonical_json(state_doc(index, at))
        times.append((time.perf_counter() - q0) * 1000)
    times.sort()
    print(f"spatial_state_v1 (doc + validation + bytes), 1000 random t: "
          f"median {statistics.median(times):.2f} ms, p95 {times[949]:.2f} ms, "
          f"max {times[-1]:.2f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
