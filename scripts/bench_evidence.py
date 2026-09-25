"""Phase 10.5 evidence endpoint benchmark (needs Postgres at TEST_DATABASE_URL).

    cd backend
    python ../scripts/bench_evidence.py

Seeds the real Singapore pair under a throwaway session id, then measures
GET /evidence/lap-comparison: the cold first request in this process and the
median of warm requests, split by the route's Server-Timing header into
db (pool + queries), pipeline (10.1B -> 10.4 -> evidence build + validation)
and serialize (canonical JSON). Removes its rows afterwards.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
DB = os.environ.get("TEST_DATABASE_URL", "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel")
WARM = 15


def _timing(header: str) -> dict[str, float]:
    return {k: float(v.split("=")[1]) for k, v in
            (part.strip().split(";") for part in header.split(","))}


async def _seed(sid: str) -> dict:
    from app.core.enums import ProvenanceClass, ProviderName, SessionType
    from app.core.models import Provenance, SessionInfo
    from app.providers.openf1.mapping import to_car_sample, to_lap
    from app.storage.db import Repository, apply_migrations, connect

    meta = json.loads((FIXTURE / "meta.json").read_text())
    pool = await connect(DB)
    await apply_migrations(pool)
    repo = Repository(pool)
    await repo.upsert_session(SessionInfo(
        session_id=sid, provider=ProviderName.OPENF1, provider_session_key="9161",
        session_type=SessionType.QUALIFYING, year=meta["year"],
        circuit_short_name=meta["circuit_short_name"],
        provenance=Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.B)))
    for d in (meta["driver_a"], meta["driver_b"]):
        lap, _ = to_lap(json.loads((FIXTURE / f"driver_{d}_lap.json").read_text()), sid)
        await repo.insert_lap(lap)
        rows = json.loads((FIXTURE / f"driver_{d}_car_data.json").read_text())
        samples = [to_car_sample(r, sid) for r in rows]
        await repo.insert_car_samples_bulk([
            (s.session_id, s.driver_number, s.ts, s.rpm, s.speed_kph, s.gear, s.throttle_pct,
             s.brake_pct, s.drs, s.provenance.provenance_class.value) for s in samples])
    await pool.close()
    return meta


async def _cleanup(sid: str) -> None:
    from app.storage.db import connect
    pool = await connect(DB)
    for table in ("telemetry_car", "laps", "sessions"):
        await pool.execute(f"DELETE FROM {table} WHERE session_id=$1", sid)
    await pool.close()


def main() -> None:
    sid = f"bench:ev:{uuid.uuid4().hex[:10]}"
    meta = asyncio.run(_seed(sid))
    os.environ["DATABASE_URL"] = DB
    try:
        from fastapi.testclient import TestClient

        from app.api import HubRegistry, create_app
        client = TestClient(create_app(HubRegistry()))
        url = (f"/api/v1/sessions/{sid}/evidence/lap-comparison?" + urlencode({
            "driver_a": meta["driver_a"], "lap_a": meta["lap_a"], "driver_b": meta["driver_b"],
            "lap_b": meta["lap_b"], "lap_length_m": meta["lap_length_m"],
            "lap_length_source": meta["lap_length_source"]}))
        t0 = time.perf_counter()
        cold = client.get(url)
        cold_ms = (time.perf_counter() - t0) * 1000
        assert cold.status_code == 200, cold.text
        warm, parts = [], []
        for _ in range(WARM):
            t0 = time.perf_counter()
            r = client.get(url)
            warm.append((time.perf_counter() - t0) * 1000)
            parts.append(_timing(r.headers["Server-Timing"]))
            assert r.content == cold.content  # deterministic bytes
        print(f"evidence_v1 {len(cold.content)} bytes, {cold.headers['X-Evidence-Id']}")
        print(f"cold request   {cold_ms:7.1f} ms  (Server-Timing {cold.headers['Server-Timing']})")
        print(f"warm median    {statistics.median(warm):7.1f} ms over {WARM} requests")
        for k in ("db", "pipeline", "serialize"):
            print(f"  {k:<10} median {statistics.median(p[k] for p in parts):6.1f} ms")
    finally:
        asyncio.run(_cleanup(sid))


if __name__ == "__main__":
    main()
