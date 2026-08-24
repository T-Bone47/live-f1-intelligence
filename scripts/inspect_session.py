"""inspect_session - DB summary + samples for an ingested session.

Usage:
    python scripts/inspect_session.py openf1:11353 [--samples 5]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _common import setup_logging

setup_logging()
import json  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.storage.db import connect  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect a stored session")
    ap.add_argument("session_id")
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    pool = await connect(get_settings().database_url)
    try:
        sess = await pool.fetchrow("SELECT * FROM sessions WHERE session_id=$1", args.session_id)
        if not sess:
            print(f"session {args.session_id} not found")
            return 1
        s = dict(sess)
        print("=" * 64)
        print(f"SESSION {s['session_id']}")
        print(f"  {s['year']} {s['session_type']} @ {s['circuit_short_name']} "
              f"[{s['status']}] provider={s['provider']}")
        print(f"  start={s['date_start']} end={s['date_end']}")
        counts = {}
        for table in ("laps", "sectors", "telemetry_car", "telemetry_location",
                      "tyre_stints", "pit_stops", "weather_points",
                      "race_control_messages", "position_updates",
                      "timing_intervals", "events"):
            n = await pool.fetchval(f"SELECT count(*) FROM {table} WHERE session_id=$1",
                                    args.session_id)
            counts[table] = int(n)
        print("ROW COUNTS:")
        for k, v in counts.items():
            print(f"  {k:<24} {v}")

        drivers = await pool.fetch(
            """SELECT sd.driver_number, d.full_name, d.name_acronym, t.display_name
               FROM session_drivers sd JOIN drivers d USING(driver_id)
               LEFT JOIN teams t ON t.team_id = d.team_id
               WHERE sd.session_id=$1 ORDER BY sd.driver_number""",
            args.session_id,
        )
        print(f"DRIVERS ({len(drivers)}):")
        for r in drivers[:30]:
            print(f"  #{r['driver_number']:<3} {r['name_acronym'] or '---'} "
                  f"{r['full_name']} ({r['display_name'] or '?'})")

        n = args.samples
        laps = await pool.fetch(
            """SELECT driver_number, lap_number, duration_s, sector1_s, sector2_s,
                      sector3_s, st_kph
               FROM laps WHERE session_id=$1 AND duration_s IS NOT NULL
               ORDER BY started_at LIMIT $2""",
            args.session_id, n,
        )
        if laps:
            print(f"LAP SAMPLES ({len(laps)}):")
            for r in laps:
                print(f"  #{r['driver_number']} L{r['lap_number']} "
                      f"{r['duration_s']:.3f}s (S1 {r['sector1_s']} "
                      f"S2 {r['sector2_s']} S3 {r['sector3_s']}) ST={r['st_kph']}")

        wx = await pool.fetch(
            "SELECT ts, air_temp_c, track_temp_c, rainfall FROM weather_points "
            "WHERE session_id=$1 ORDER BY ts DESC LIMIT $2",
            args.session_id, n,
        )
        if wx:
            print(f"WEATHER (latest {len(wx)}):")
            for r in wx:
                print(f"  {r['ts']:%H:%M:%S} air={r['air_temp_c']}C track={r['track_temp_c']}C "
                      f"rain={r['rainfall']}")

        rcms = await pool.fetch(
            """SELECT ts, category, flag, marshal_sector, message
               FROM race_control_messages WHERE session_id=$1
               ORDER BY ts LIMIT $2""",
            args.session_id, n,
        )
        if rcms:
            print(f"RACE CONTROL ({len(rcms)} shown of "
                  f"{counts['race_control_messages']}):")
            for r in rcms:
                print(f"  {r['ts']:%H:%M:%S} [{r['category']}"
                      f"{('/' + str(r['flag'])) if r['flag'] else ''}] {r['message']}")

        ev = await pool.fetch(
            """SELECT event_type, count(*) AS c FROM events WHERE session_id=$1
               GROUP BY event_type ORDER BY c DESC""",
            args.session_id,
        )
        print(f"EVENT TYPES ({len(ev)}):")
        for r in ev:
            print(f"  {r['event_type']:<28} {r['c']}")
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
