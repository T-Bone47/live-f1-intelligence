"""backtest_analysis - Phase 2 acceptance + determinism baseline.

Runs the full AnalysisEngine over a recorded session through ReplayProvider
(provider-independent), then:

1. prints intelligence-event summary + snapshot highlights
2. writes/compares a determinism baseline (same input => identical output)
3. benchmarks events/sec, per-event latency, memory

Usage:
    python scripts/backtest_analysis.py recordings/openf1-11353-race \
        [--baseline backend/tests/fixtures/backtest_baseline_11353.json] \
        [--update-baseline]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import tracemalloc
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analysis import AnalysisEngine  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.ingest.pipeline import IngestPipeline  # noqa: E402
from app.providers.replay import ReplayProvider  # noqa: E402


async def run(recording: str) -> tuple[AnalysisEngine, dict]:
    provider = ReplayProvider(Path(recording))
    provider.set_speed(0)
    session = await provider.resolve_session(recording)
    pipeline = IngestPipeline(session_id=session.session_id)
    engine = AnalysisEngine(session_id="openf1:11353")

    async def on_env(env) -> None:  # noqa: ANN001
        engine.process_envelope(env)

    pipeline.bus.subscribe("analysis", on_env)

    tracemalloc.start()
    t0 = time.perf_counter()
    latencies: list[float] = []
    count = 0
    async for item in provider.run(session):
        e0 = time.perf_counter()
        count += await pipeline.process(item)
        latencies.append((time.perf_counter() - e0) * 1000)
    elapsed = time.perf_counter() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    bench = {
        "events_processed": count,
        "elapsed_s": round(elapsed, 2),
        "events_per_sec": round(count / max(elapsed, 1e-6), 1),
        "latency_ms_p50": round(sorted(latencies)[len(latencies) // 2], 4),
        "latency_ms_p95": round(
            sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * 0.95))], 4),
        "peak_memory_mb": round(peak / 1e6, 1),
    }
    return engine, bench


def summarize(engine: AnalysisEngine) -> dict:
    snap = engine.snapshot_dict()
    by_type: dict[str, int] = {}
    for ev in engine.sig.events:
        by_type[ev.event_type] = by_type.get(ev.event_type, 0) + 1
    deg = engine.degradation_summary()
    return {
        "calc_version": snap.get("calc_version"),
        "phase": snap["phase"],
        "track_flag": snap["track_flag"],
        "current_lap": snap["current_lap"],
        "leaderboard_top5": [
            {"pos": r["position"], "driver": r["driver_number"],
             "pb": r["personal_best_s"], "rolling5": r["rolling5_s"],
             "tyre_age": r["tyre_age"], "compound": r["compound"]}
            for r in snap["leaderboard"][:5]
        ],
        "fastest_lap": snap["fastest_lap"],
        "sector_leaders": snap["sector_leaders"],
        "event_counts": dict(sorted(by_type.items())),
        "degradation_sample": {
            str(k): v for k, v in list(sorted(deg.items()))[:3]
        },
    }


async def main() -> int:
    recording = sys.argv[1] if len(sys.argv) > 1 else "recordings/openf1-11353-race"
    baseline_arg = None
    update = "--update-baseline" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--baseline":
            baseline_arg = sys.argv[i + 1]

    get_settings()
    print(f"BACKTEST over {recording}")
    engine, bench = await run(recording)
    summary = summarize(engine)

    print(json.dumps(bench, indent=2))
    print(json.dumps(summary, indent=2))

    if baseline_arg:
        bp = Path(baseline_arg)
        if update or not bp.exists():
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_text(json.dumps({"bench": bench, "summary": summary},
                                     indent=2, sort_keys=True), encoding="utf-8")
            print(f"baseline written: {bp}")
        else:
            expected = json.loads(bp.read_text(encoding="utf-8"))
            if expected["summary"] == summary:
                print("DETERMINISM CHECK: PASS (summary identical to baseline)")
            else:
                print("DETERMINISM CHECK: FAIL")
                for k in set(expected["summary"]) | set(summary):
                    if expected["summary"].get(k) != summary.get(k):
                        print(f"  differs: {k}")
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
