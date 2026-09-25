"""Record REAL Blacktop + Jolpica responses for one event as test fixtures.

Writes verbatim JSON bodies (never the API key, never request headers) to
backend/tests/fixtures/blacktop/<year>-<event-slug>/ plus a meta.json with
provenance: endpoint, params, row counts and the month quota left afterwards.

Usage (from backend/):
    .\\.venv\\Scripts\\python.exe ..\\scripts\\record_blacktop_fixtures.py \\
        --year 2023 --event-name "Singapore Grand Prix"

Costs ~6 Blacktop requests (free tier: 7,500/month, 60/min).
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

from app.config import get_settings
from app.providers.blacktop.client import BlacktopClient
from app.providers.jolpica.client import JolpicaClient

FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "blacktop"


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def _dump(path: Path, body: object) -> None:
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--event-name", required=True)
    args = ap.parse_args()

    settings = get_settings()
    if not settings.blacktop_api_key:
        print("FAILED: BLACKTOP_API_KEY not set in backend/.env")
        return 2

    bt = BlacktopClient(api_key=settings.blacktop_api_key, base_url=settings.blacktop_api_base_url)
    jp = JolpicaClient()
    calls: list[dict] = []
    out = FIXTURES / f"{args.year}-{_slug(args.event_name)}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        events = await bt.events(args.year)
        calls.append({"endpoint": "/v1/formula1/events", "params": {"year": args.year},
                      "rows": len(events)})
        _dump(out / "events.json", events)

        matches = [e for e in events if e.get("name") == args.event_name]
        if len(matches) != 1:
            print(f"FAILED: expected one event named {args.event_name!r}, got {len(matches)}")
            return 2
        event = matches[0]
        detail = await bt.event(event["id"])
        calls.append({"endpoint": f"/v1/formula1/events/{event['id']}", "rows": 1})
        _dump(out / "event.json", detail)

        for sess in detail.get("schedule") or []:
            if sess.get("type") not in ("race", "qualifying"):
                continue
            rows = await bt.session_results(event["id"], sess["id"])
            calls.append({
                "endpoint": f"/v1/formula1/events/{event['id']}/sessions/{sess['id']}/results",
                "session_type": sess["type"], "rows": len(rows)})
            _dump(out / f"results_{sess['type']}.json", rows)

        standings = await bt.driver_standings(args.year)
        calls.append({"endpoint": "/v1/formula1/standings/drivers", "params": {"year": args.year},
                      "rows": len(standings)})
        _dump(out / "standings_drivers.json", standings)

        # Jolpica counterpart for the same event, matched by race DATE: Blacktop
        # has no round numbers and its list includes testing + cancelled events.
        schedule = await jp.season_schedule(args.year)
        race_day = next((s["startTime"][:10] for s in detail.get("schedule") or []
                         if s.get("type") == "race"), None)
        jmatch = [r for r in schedule if r.get("date") == race_day]
        if len(jmatch) != 1:
            print(f"FAILED: Jolpica has {len(jmatch)} races on {race_day}")
            return 2
        rnd = jmatch[0]["round"]
        _dump(out / "jolpica_race_results.json", await jp.race_results(args.year, rnd))
        _dump(out / "jolpica_quali_results.json", await jp.qualifying_results(args.year, rnd))
        _dump(out / "jolpica_driver_standings.json", await jp.driver_standings(args.year))
        calls.append({"endpoint": f"jolpica {args.year}/{rnd} results+qualifying+driverStandings",
                      "matched_by": f"race date {race_day}"})
    finally:
        await bt.aclose()
        await jp.aclose()

    _dump(out / "meta.json", {
        "kind": "REAL provider data - raw Blacktop + Jolpica bodies, unmodified",
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "script": "scripts/record_blacktop_fixtures.py",
        "year": args.year,
        "event_name": args.event_name,
        "blacktop_month_quota_remaining": bt.last_rate.get("month_remaining"),
        "calls": calls,
    })
    print(f"wrote {out} ({len(calls)} call groups); Blacktop month quota left: "
          f"{bt.last_rate.get('month_remaining')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
