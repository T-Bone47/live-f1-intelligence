"""serve_evidence_dev - local API for the Phase 10.6 Evidence Workbench.

Seeds the REAL Singapore pair (scripts/fixtures/real-openf1-pair, raw
OpenF1 rows, unmodified) under its real session id `openf1:9161`, then
serves the REST API on 127.0.0.1:8000 so `npm run dev` (Vite proxies /api)
can load /evidence against real evidence. Seeding is idempotent
(ON CONFLICT DO NOTHING). Nothing is synthesized.

It uses its OWN database, `f1intel_evidence_dev` (created if missing), never
the test database: the DB tests insert provider_session_key "9161" too, and a
persistent real row there makes them fail on the sessions unique key.

    cd backend
    .\\.venv\\Scripts\\python.exe ..\\scripts\\serve_evidence_dev.py
    # other server: --database-url postgresql://user:pass@host:5432/f1intel_evidence_dev

Then open http://localhost:5173/evidence and pick the "Singapore 2023 Q"
preset (driver 55 lap 19 vs driver 63 lap 16).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
DEFAULT_DB = "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel_evidence_dev"


async def ensure_database(db_url: str) -> None:
    """CREATE DATABASE <name> if it does not exist (via the server's `postgres` db)."""
    import asyncpg

    base, name = db_url.rsplit("/", 1)
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise SystemExit(f"refusing unusual database name {name!r}")
    conn = await asyncpg.connect(f"{base}/postgres")
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def seed(db_url: str) -> str:
    from app.core.enums import ProvenanceClass, ProviderName, SessionType
    from app.core.models import Provenance, SessionInfo
    from app.providers.openf1.mapping import to_car_sample, to_lap
    from app.storage.db import Repository, apply_migrations, connect

    meta = json.loads((FIXTURE / "meta.json").read_text())
    sid = f"openf1:{meta['session_key']}"
    pool = await connect(db_url)
    try:
        await apply_migrations(pool)
        repo = Repository(pool)
        await repo.upsert_session(SessionInfo(
            session_id=sid, provider=ProviderName.OPENF1,
            provider_session_key=str(meta["session_key"]),
            session_type=SessionType.QUALIFYING, year=meta["year"],
            circuit_short_name=meta["circuit_short_name"],
            provenance=Provenance(provider=ProviderName.OPENF1,
                                  provenance_class=ProvenanceClass.B)))
        for d in (meta["driver_a"], meta["driver_b"]):
            lap, _ = to_lap(json.loads((FIXTURE / f"driver_{d}_lap.json").read_text()), sid)
            await repo.insert_lap(lap)
            rows = json.loads((FIXTURE / f"driver_{d}_car_data.json").read_text())
            samples = [to_car_sample(r, sid) for r in rows]
            await repo.insert_car_samples_bulk([
                (s.session_id, s.driver_number, s.ts, s.rpm, s.speed_kph, s.gear,
                 s.throttle_pct, s.brake_pct, s.drs, s.provenance.provenance_class.value)
                for s in samples])
    finally:
        await pool.close()
    return sid


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the real pair and serve the REST API.")
    ap.add_argument("--database-url", default=DEFAULT_DB)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-serve", action="store_true", help="seed only")
    args = ap.parse_args()

    asyncio.run(ensure_database(args.database_url))
    sid = asyncio.run(seed(args.database_url))
    print(f"seeded real pair under {sid} in {args.database_url.rsplit('/', 1)[1]}")
    if args.no_serve:
        return

    import uvicorn

    from app.api import HubRegistry, create_app
    from app.config import get_settings

    os.environ["DATABASE_URL"] = args.database_url
    get_settings.cache_clear()
    uvicorn.run(create_app(HubRegistry()), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
