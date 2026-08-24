"""Minimal probe: why don't delta frames reach the client during replay?"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.providers.replay import ReplayProvider  # noqa: E402
from app.realtime.hub import SessionHub  # noqa: E402

RECORDING = Path(__file__).resolve().parent.parent / "recordings" / (
    "openf1-11353-race")


async def main() -> None:
    provider = ReplayProvider(RECORDING)
    provider.set_speed(0)
    session = await provider.resolve_session(str(RECORDING))
    hub = SessionHub(session_id=f"replay:{RECORDING.name}")

    conn = await hub.subscribe("probe")
    print("initial kind:", (await hub.next_for(conn)).kind)

    pub = asyncio.create_task(hub.run())

    async def feed():
        async for item in provider.run(session):
            await hub.feed(item)

    ft = asyncio.create_task(feed())
    kinds: dict[str, int] = {}
    t_end = asyncio.get_event_loop().time() + 12
    while asyncio.get_event_loop().time() < t_end:
        try:
            f = await asyncio.wait_for(hub.next_for(conn), timeout=3)
        except asyncio.TimeoutError:
            continue
        kinds[f.kind] = kinds.get(f.kind, 0) + 1
    print("client saw:", kinds)
    m = hub.metrics.as_dict()
    print("diff p50:", m["diff_latency_ms"], "| ev/s:", m["events_per_sec"])
    ft.cancel()
    hub.stop()
    pub.cancel()


if __name__ == "__main__":
    asyncio.run(main())
