"""Backfill lap-correction ledger from stored RCM messages (dev tool).

Demonstrates the tombstone path on real data without re-fetching:
reads deletion messages from race_control_messages, builds canonical
LapCorrection records, applies them through the repository.
"""

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.ingest.corrections import build_correction  # noqa: E402
from app.storage.db import Repository, connect  # noqa: E402


async def backfill(session_id: str) -> int:
    pool = await connect(get_settings().database_url)
    repo = Repository(pool)
    try:
        rows = await pool.fetch(
            "SELECT ts, message FROM race_control_messages "
            "WHERE session_id=$1 AND message LIKE '%DELETED%' "
            "AND message NOT LIKE '%REINSTATED%'",
            session_id,
        )
        print(f"deletion rcm rows: {len(rows)}")
        applied = 0
        for r in rows:
            c = build_correction(r["message"], session_id, None, r["ts"], "A")
            if c and await repo.insert_lap_correction(c):
                applied += 1
        print(f"corrections applied: {applied}")
        stats = await pool.fetchrow(
            "SELECT (SELECT count(*) FROM lap_corrections) AS corr, "
            "(SELECT count(*) FROM laps WHERE deleted) AS deleted_laps"
        )
        print(f"ledger: {dict(stats)}")
        sample = await pool.fetch(
            "SELECT lc.driver_number AS num, lc.lap_number AS lap, lc.reason, "
            "l.duration_s FROM lap_corrections lc JOIN laps l "
            "ON l.session_id=lc.session_id AND l.driver_number=lc.driver_number "
            "AND l.lap_number=lc.lap_number LIMIT 5"
        )
        for s in sample:
            print(f"  #{s['num']} L{s['lap']} {s['duration_s']}s -> DELETED ({s['reason']})")
        return applied
    finally:
        await pool.close()


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "openf1:11353"
    asyncio.run(backfill(sid))
