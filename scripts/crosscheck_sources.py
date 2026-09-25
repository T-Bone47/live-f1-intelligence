"""Cross-check a season: Jolpica (primary) vs Blacktop (challenger), LIVE.

For every race of the season: race + qualifying results; plus final driver
standings. Events are matched by race DATE +-1 day, uniquely (Blacktop has
no round numbers; its list includes testing and cancelled events). Never merges values -
prints every CONFLICT / missing row so a human can decide.

Usage (from backend/):
    .\\.venv\\Scripts\\python.exe ..\\scripts\\crosscheck_sources.py --year 2024 [--json out.json]

Cost: ~2 + races*2 Blacktop requests (free tier 7,500/month).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analysis.source_crosscheck import (
    crosscheck_quali,
    crosscheck_race,
    crosscheck_standings,
)
from app.config import get_settings
from app.providers.blacktop import mapping as btm
from app.providers.blacktop.client import BlacktopClient, BlacktopError
from app.providers.jolpica import mapping as jpm
from app.providers.jolpica.client import JolpicaClient


def _row(rep, label: str) -> dict:
    kinds = Counter(d.resolution.value for d in rep.discrepancies)
    return {"event": label, "kind": rep.kind, "compared": rep.compared,
            "conflicts": kinds.get("CONFLICT", 0), "no_contest": kinds.get("NO_CONTEST", 0),
            "details": [{"subject": d.subject, "field": d.field, "resolution": d.resolution.value,
                         "jolpica": d.primary_value, "blacktop": d.challenger_value}
                        for d in rep.discrepancies]}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    s = get_settings()
    if not s.blacktop_api_key:
        print("FAILED: BLACKTOP_API_KEY not set")
        return 2

    bt = BlacktopClient(api_key=s.blacktop_api_key, base_url=s.blacktop_api_base_url)
    jp = JolpicaClient()
    rows: list[dict] = []
    try:
        schedule = await jp.season_schedule(args.year)
        events = await bt.events(args.year)
        by_race_day: dict[str, list] = {}
        for ev in events:
            for sess in ev.get("schedule") or []:
                if sess.get("type") == "race" and sess.get("startTime"):
                    by_race_day.setdefault(sess["startTime"][:10], []).append((ev, sess))
        for race in schedule:
            label = f"R{race['round']} {race['raceName']}"
            # +-1 day: a night race (Las Vegas 2024) is Saturday local / Jolpica
            # but Sunday UTC in Blacktop's startTime. Still must be unique.
            day = date.fromisoformat(race["date"])
            hits = [h for d in (day - timedelta(days=1), day, day + timedelta(days=1))
                    for h in by_race_day.get(d.isoformat(), [])]
            if len(hits) != 1:
                rows.append({"event": label, "kind": "match", "error":
                             f"{len(hits)} Blacktop races on {race.get('date')}"})
                continue
            ev, race_sess = hits[0]
            quali_sess = next((x for x in ev["schedule"] if x.get("type") == "qualifying"), None)
            try:
                jr = [jpm.result_row_to_race_result(r, "x")
                      for r in await jp.race_results(args.year, race["round"])]
                if not jr:
                    rows.append({"event": label, "kind": "race",
                                 "error": "no Jolpica results (not run yet?)"})
                    continue
                br = [btm.race_row_to_result(r, "x")
                      for r in await bt.session_results(ev["id"], race_sess["id"])]
                rows.append(_row(crosscheck_race(jr, br), label))
                if quali_sess:
                    jq = [jpm.quali_row_to_result(r, "x")
                          for r in await jp.qualifying_results(args.year, race["round"])]
                    bq = [btm.quali_row_to_result(r, "x")
                          for r in await bt.session_results(ev["id"], quali_sess["id"])]
                    rows.append(_row(crosscheck_quali(jq, bq), label))
            except (BlacktopError, ValueError) as exc:
                rows.append({"event": label, "kind": "error", "error": str(exc)})
        js = [jpm.standing_row_to_entry(r, args.year) for r in await jp.driver_standings(args.year)]
        bs = [btm.standing_row_to_entry(r, args.year) for r in await bt.driver_standings(args.year)]
        rows.append(_row(crosscheck_standings(js, bs), f"{args.year} driver standings"))
    finally:
        await bt.aclose()
        await jp.aclose()

    tot: Counter = Counter()
    for r in rows:
        if "error" in r:
            print(f"  ! {r['event']:<34} {r['kind']:<9} {r['error']}")
            tot["errors"] += 1
            continue
        tot["compared"] += r["compared"]
        tot["conflicts"] += r["conflicts"]
        tot["no_contest"] += r["no_contest"]
        flag = "OK      " if not r["conflicts"] else "CONFLICT"
        print(f"  {flag} {r['event']:<34} {r['kind']:<9} compared {r['compared']:>2}  "
              f"conflicts {r['conflicts']}  no-contest {r['no_contest']}")
        for d in r["details"]:
            if d["resolution"] == "CONFLICT" or d["field"] == "row":
                print(f"        {d['resolution']:<10} {d['subject']:<12} {d['field']:<15} "
                      f"jolpica={d['jolpica']!r} blacktop={d['blacktop']!r}")
    print(f"TOTAL {args.year}: {dict(tot)} | Blacktop month quota left: "
          f"{bt.last_rate.get('month_remaining')}")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str),
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
