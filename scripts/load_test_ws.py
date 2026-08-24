"""load_test_ws - Phase 3 load test: N websocket clients vs replay runtime.

Hosts the realtime gateway in-process (uvicorn server task) driven by the
Dutch GP recording at max speed, then connects N clients that read frames for
a fixed duration, measuring per-client frame rates and delivery latency
(same-machine clock). Server-side metrics come from hub.metrics.

Usage:
    python scripts/load_test_ws.py --clients 50 --duration 20 \
        recordings/openf1-11353-race [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import websockets  # noqa: E402


async def run(args) -> dict:
    import uvicorn

    from app.api import HubRegistry, create_app
    from app.providers.replay import ReplayProvider
    from app.realtime.hub import SessionHub

    rec_dir = Path(args.recording)
    provider = ReplayProvider(rec_dir)
    provider.set_speed(0)  # max speed = worst case
    session = await provider.resolve_session(str(rec_dir))

    hub = SessionHub(session_id="openf1:11353")
    hub.metrics.provider_name = "replay-loadtest"
    registry = HubRegistry()
    registry.register(hub)

    async def upstream() -> None:
        async for item in provider.run(session):
            await hub.feed(item)
            await asyncio.sleep(0)  # yield to event loop fairly

    app = create_app(registry)

    async def client(client_id: int, results: list):
        port = args.port
        uri = f"ws://127.0.0.1:{port}/ws/session/{hub.session_id}"
        frames = 0
        deltas = 0
        dropped_local = 0
        latencies: list[float] = []
        try:
            async with websockets.connect(uri, max_size=8 * 1024 * 1024,
                                          open_timeout=10) as ws:
                deadline = time.monotonic() + args.duration
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except (asyncio.TimeoutError, asyncio.TimeoutError):
                        continue
                    frames += 1
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    if msg.get("kind") == "delta":
                        deltas += 1
                        ts_raw = msg.get("ts")
                        if ts_raw:
                            try:
                                from datetime import datetime, timezone

                                server_dt = datetime.fromisoformat(ts_raw)
                                if server_dt.tzinfo is None:
                                    server_dt = server_dt.replace(tzinfo=timezone.utc)
                                delta_ms = (
                                    datetime.now(timezone.utc) - server_dt
                                ).total_seconds() * 1000
                                if 0 <= delta_ms < 60_000:
                                    latencies.append(delta_ms)
                            except ValueError:
                                pass
                    elif msg.get("kind") in ("evicted",):
                        dropped_local += 1
                        break
        except Exception as exc:  # noqa: BLE001
            results.append({"client": client_id, "error": f"{type(exc).__name__}: {exc}"[:120]})
            return
        results.append({
            "client": client_id, "frames": frames, "deltas": deltas,
            "frames_per_sec": round(frames / args.duration, 1),
            "latency_p50_ms": round(statistics.median(latencies), 2) if latencies else None,
            "latency_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 2)
            if len(latencies) > 1 else None,
            "evicted": dropped_local > 0,
        })

    config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="critical")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(60):
        if server.started:
            break
        await asyncio.sleep(0.25)

    upstream_task = asyncio.create_task(upstream())
    publish_task = asyncio.create_task(hub.run())
    t_start = time.monotonic()
    cpu_start = time.process_time()

    results: list[dict] = []
    clients = [asyncio.create_task(client(i, results)) for i in range(args.clients)]
    await asyncio.sleep(args.duration + 15)   # generous grace: single-loop
    # saturation can delay client teardown; cancellations are recorded as
    # incomplete rather than errors
    for c in clients:
        if not c.done():
            c.cancel()
        else:
            continue

    cpu_used = time.process_time() - cpu_start
    wall = time.monotonic() - t_start
    hub.stop()
    upstream_task.cancel()
    publish_task.cancel()
    server.should_exit = True
    await server_task

    ok = [r for r in results if "error" not in r]
    total_frames = sum(r.get("frames", 0) for r in ok)
    summary = {
        "clients_requested": args.clients,
        "clients_completed_ok": len(ok),
        "clients_errored": len(results) - len(ok),
        "total_frames_received": total_frames,
        "aggregate_frames_per_sec": round(total_frames / args.duration, 1),
        "server_cpu_seconds_process_wide": round(cpu_used, 1),
        "cpu_utilization_est_pct": round(100 * cpu_used / max(wall, 1e-6), 1),
        "hub_metrics": hub.metrics.as_dict(),
        "per_client_sample": ok[:5],
        "latency_p50_all_clients_ms": round(statistics.median(
            [r["latency_p50_ms"] for r in ok if r.get("latency_p50_ms")]), 2)
        if any(r.get("latency_p50_ms") for r in ok) else None,
        "errors_sample": [r for r in results if "error" in r][:3],
    }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", nargs="?", default="recordings/openf1-11353-race")
    ap.add_argument("--clients", type=int, default=10)
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--duration", type=float, default=15.0)
    ap.add_argument("--json", default=None, help="write result JSON to file")
    args = ap.parse_args()

    result = asyncio.run(run(args))
    print(json.dumps(result, indent=2))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
