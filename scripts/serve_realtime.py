"""serve_realtime - host the Phase-3 realtime gateway for one session.

REPLAY AS REAL-TIME (default demo):
    python scripts/serve_realtime.py --mode replay recordings/openf1-11353-race [--speed 5]

LIVE:
    python scripts/serve_realtime.py --mode live --ref latest [--provider openf1]

Then point any client at:
    REST  http://127.0.0.1:8000/api/v1/sessions/{id}/snapshot
    WS    ws://127.0.0.1:8000/ws/session/{id}
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("serve_realtime")


async def build_runtime(args) -> tuple:  # noqa: ANN202
    import uvicorn

    from app.api import HubRegistry, create_app
    from app.config import get_settings
    from app.providers.openf1.client import OpenF1Client
    from app.providers.openf1.provider import OpenF1Provider
    from app.providers.replay import ReplayProvider
    from app.realtime.hub import SessionHub

    settings = get_settings()
    if args.mode == "replay":
        rec_dir = Path(args.recording)
        provider = ReplayProvider(rec_dir)
        provider.set_speed(float(args.speed or 0))
        session = await provider.resolve_session(str(rec_dir))
        session_id = f"replay:{rec_dir.name}"
    else:
        client = OpenF1Client(settings)
        provider = OpenF1Provider(client, settings)
        session = await provider.resolve_session(args.ref or "latest")
        session_id = session.session_id

    hub = SessionHub(session_id=session_id)
    hub.metrics.provider_name = args.mode
    hub.metrics.provider_status = "CONNECTING"
    registry = HubRegistry()
    registry.register(hub)

    # Phase 6: grounded AI runtime (mock provider by default - no key needed)
    from app.ai.gateway import LLMGateway
    from app.ai.jobs import AIRuntime
    from app.ai.providers import build_provider
    from app.config import get_settings as _gs

    s2 = _gs()
    api_key = (s2.gemini_api_key if s2.llm_provider == "gemini"
               else s2.llm_api_key)
    base_url = (None if s2.llm_provider == "gemini"  # gemini default endpoint
                else s2.llm_base_url)
    provider = build_provider(s2.llm_provider, base_url=base_url,
                              api_key=api_key, model=s2.llm_model)
    ai_runtime = AIRuntime(
        LLMGateway(provider, min_call_interval_s=s.llm_min_call_interval_s),
        auto_enabled=s.llm_auto_commentary,
        get_mode=lambda: args.mode.upper())
    hub.attach_ai(ai_runtime)
    await ai_runtime.start_worker()
    print(f"AI race engineer: provider={provider.name} "
          f"auto={s2.llm_auto_commentary}")

    async def upstream() -> None:
        print("UPSTREAM TASK ENTERED", flush=True)
        # Runs the async provider in a DEDICATED THREAD/LOOP and hands items
        # to the gateway loop via run_coroutine_threadsafe - backpressure is
        # preserved (the thread blocks until hub.feed completes) while the
        # serving event loop stays responsive even at max-speed replay.
        import threading

        hub.metrics.provider_status = "CONNECTED"
        main_loop = asyncio.get_running_loop()

        def worker() -> None:
            print("WORKER THREAD ENTERED", flush=True)

            async def collect() -> None:
                log.info("upstream started (%s)", args.mode)
                n = 0
                async for item in provider.run(session):
                    fut = asyncio.run_coroutine_threadsafe(
                        hub.feed(item), main_loop)
                    fut.result()
                    n += 1
                    if n % 100_000 == 0:
                        print(f"fed {n}", flush=True)
                hub.engine.flush_deferred()
                log.info("upstream exhausted")

            asyncio.run(collect())

        threading.Thread(target=worker, daemon=True,
                         name="provider-upstream").start()

    app = create_app(registry)
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    server = uvicorn.Server(config)
    return server, upstream, hub


async def amain() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("recording", nargs="?", default="recordings/openf1-11353-race")
    ap.add_argument("--ref", default="latest")
    ap.add_argument("--speed", default="0", help="replay speed; 0=max")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    server, upstream, hub = await build_runtime(args)
    tasks = [asyncio.create_task(upstream()), asyncio.create_task(hub.run())]
    print(f"REALTIME GATEWAY on {args.host}:{args.port} "
          f"(session={hub.session_id})")
    print(f"WS   ws://{args.host}:{args.port}/ws/session/{hub.session_id}")
    print(f"REST http://{args.host}:{args.port}/api/v1/sessions/{hub.session_id}/snapshot")
    serve_task = asyncio.create_task(server.serve())

    def _watch(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            log.error("gateway server crashed: %r", t.exception())
    serve_task.add_done_callback(_watch)

    # upstream is a fire-and-forget thread launcher; serve_task governs life
    done, _pending = await asyncio.wait({serve_task})
    if serve_task.exception():
        raise serve_task.exception()  # type: ignore[arg-type]
    hub.stop()
    await ai_runtime.stop()
    for t in tasks:
        t.cancel()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
