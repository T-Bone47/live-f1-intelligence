"""replay_session - prove recorded canonical events flow through the same
pipeline interfaces (ReplayProvider -> pipeline -> bus), without re-fetching.

Usage:
    python scripts/replay_session.py recordings/openf1-11353-race [--speed 0]
    [--max-events 2000] [--persist]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from _common import setup_logging

setup_logging()
import logging  # noqa: E402

log = logging.getLogger("replay_session")

from app.config import get_settings  # noqa: E402
from app.core.events import EventBus  # noqa: E402
from app.ingest.persistence import PersistenceSubscriber  # noqa: E402
from app.ingest.pipeline import IngestPipeline  # noqa: E402
from app.providers.replay import ReplayProvider  # noqa: E402
from app.storage.db import Repository, connect  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Replay a recorded session")
    ap.add_argument("recording", type=str, help="path to recording directory")
    ap.add_argument("--speed", type=float, default=0.0,
                    help="playback speed; 0 = as fast as possible")
    ap.add_argument("--max-events", type=int, default=5000)
    ap.add_argument("--persist", action="store_true",
                    help="write replayed events to DB with origin=replay")
    args = ap.parse_args()

    rec_dir = Path(args.recording)
    if not rec_dir.exists():
        print(f"recording not found: {rec_dir}")
        return 2

    provider = ReplayProvider(rec_dir)
    print("CONNECTING to recording ...")
    session = await provider.resolve_session(str(rec_dir))
    provider.set_speed(args.speed)
    print(
        f"SESSION FOUND: {session.session_id} {session.year} "
        f"{session.session_type.value} [replay speed={args.speed or 'max'}]"
    )

    settings = get_settings()
    pool = await connect(settings.database_url) if args.persist else None
    bus = EventBus()
    persistence = None
    if pool:
        from app.storage.db import apply_migrations

        applied = await apply_migrations(pool)
        if applied:
            print(f"migrations applied: {applied}")
        persistence = PersistenceSubscriber(Repository(pool))
        bus.subscribe("db", persistence.__call__)

    pipeline = IngestPipeline(session_id=f"replay:{rec_dir.name}", bus=bus)

    print("RECEIVING DATA (replay) ...")
    count = 0
    types_seen: dict[str, int] = {}
    try:
        async for item in provider.run(session):
            n = await pipeline.process(item)
            count += n
            if n:
                env_types = item.payload.get("__envelope", {}).get("event_type", "?")
                types_seen[env_types] = types_seen.get(env_types, 0) + 1
            if count % 100000 < 8:
                print(f"  replayed: {count}", flush=True)
            if count >= args.max_events:
                break
        status = "COMPLETE"
    except FileNotFoundError as exc:
        print(f"FAILED: {exc}")
        status = "FAILED"
    if persistence:
        await persistence.flush()
    await bus.stop()

    q = pipeline.quality.report()
    print("\nSTOPPED -", status)
    print(f"events replayed : {count}")
    print(f"duplicates      : {q['duplicate_events']} (dedupe works across live+replay)")
    print(f"malformed       : {q['malformed_events']}")
    top = sorted(types_seen.items(), key=lambda kv: -kv[1])[:12]
    for t, c in top:
        print(f"  {t:<28} {c}")
    if persistence:
        print(f"DB rows written : {persistence.written} (origin=replay)")
    if pool:
        await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
