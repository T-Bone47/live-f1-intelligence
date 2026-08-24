"""Diagnose RC timeline + lap classification rates over the stored session."""

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.storage.db import connect  # noqa: E402
from app.analysis.race_control import RaceControlState  # noqa: E402


async def diag() -> None:
    pool = await connect(get_settings().database_url)
    rows = await pool.fetch(
        "SELECT ts, category, flag, message FROM race_control_messages "
        "WHERE session_id=$1 ORDER BY ts",
        "openf1:11353",
    )
    rc = RaceControlState()
    for r in rows:
        rc.fold_rcm(r["ts"], r["message"], r["category"], r["flag"])
    rc.close_all(rows[-1]["ts"])
    print("phase:", rc.phase().value)
    print("open at end:", [(p.kind, str(p.start.time())) for p in rc._open.values()])
    print("closed periods:", len(rc.periods))
    for p in rc.periods[:15]:
        end_s = p.end.time() if p.end else None
        print(f"  {p.kind:<14} {p.start.time()} -> {end_s}")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(diag())
