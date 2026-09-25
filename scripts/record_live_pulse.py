"""Record REAL RapidAPI F1 Live Pulse responses as fixtures - quota-guarded.

The free plan allows 20 requests per ~23-day cycle, so run this ONLY during a
live session and only for the routes you need. Each route costs 1 request.
The quota ledger (backend/.quota/f1_live_pulse.json, gitignored) refuses to
spend the last `F1_LIVE_PULSE_RESERVE_REQUESTS` requests.

Usage (from backend/):
    .\\.venv\\Scripts\\python.exe ..\\scripts\\record_live_pulse.py --status
    .\\.venv\\Scripts\\python.exe ..\\scripts\\record_live_pulse.py sessionInfo timingData lapTimes:tla=SAI

Writes backend/tests/fixtures/f1_live_pulse/<UTC stamp>/<route>.json (verbatim
bodies, no key, no headers) + meta.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import BACKEND_ROOT, get_settings
from app.providers.f1_live_pulse.client import (
    ROUTES,
    LivePulseClient,
    LivePulseError,
    LivePulseQuotaExhausted,
)

LEDGER = BACKEND_ROOT / ".quota" / "f1_live_pulse.json"
FIXTURES = BACKEND_ROOT / "tests" / "fixtures" / "f1_live_pulse"


def _parse(spec: str) -> tuple[str, dict[str, str]]:
    route, _, rest = spec.partition(":")
    params = dict(p.split("=", 1) for p in rest.split(",") if "=" in p)
    return route, params


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("routes", nargs="*", help=f"route[:k=v,...]; one of {sorted(ROUTES)}")
    ap.add_argument("--status", action="store_true", help="print the ledger; costs nothing")
    args = ap.parse_args()
    s = get_settings()
    key = s.f1_live_pulse_rapidapi_key
    if not key:
        print("FAILED: F1_LIVE_PULSE_RAPIDAPI_KEY not set in backend/.env")
        return 2
    client = LivePulseClient(api_key=key, host=s.f1_live_pulse_rapidapi_host,
                             base_url=s.f1_live_pulse_base_url, ledger_path=LEDGER,
                             reserve=s.f1_live_pulse_reserve_requests,
                             timeout=s.rapidapi_timeout_seconds)
    try:
        print(f"quota: remaining={client.remaining} limit={client.limit} "
              f"reset={client.reset_at.isoformat() if client.reset_at else None} "
              f"(None = unknown until the first response)")
        if args.status or not args.routes:
            return 0
        specs = [_parse(r) for r in args.routes]
        bad = [r for r, _ in specs if r not in ROUTES]
        if bad:
            print(f"FAILED: unknown routes {bad}")
            return 2
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = FIXTURES / stamp
        out.mkdir(parents=True, exist_ok=True)
        calls = []
        for route, params in specs:
            try:
                body = await client.get(route, params)
            except LivePulseError as exc:
                print(f"  {route}: {type(exc).__name__}: {exc}")
                calls.append({"route": route, "params": params, "error": str(exc)})
                if isinstance(exc, LivePulseQuotaExhausted):
                    break
                continue
            suffix = "_".join(f"{k}-{v}" for k, v in params.items())
            name = f"{route}{'_' + suffix if suffix else ''}.json"
            (out / name).write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
            calls.append({"route": route, "params": params, "file": name})
            print(f"  {route}: saved {name}; remaining {client.remaining}")
        (out / "meta.json").write_text(json.dumps({
            "kind": "REAL provider data - raw RapidAPI F1 Live Pulse bodies, unmodified",
            "retrieved_at_utc": datetime.now(UTC).isoformat(),
            "script": "scripts/record_live_pulse.py",
            "quota_remaining_after": client.remaining,
            "calls": calls,
        }, indent=1), encoding="utf-8")
        print(f"wrote {out}")
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
