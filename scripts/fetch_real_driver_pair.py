"""Acquire a REAL same-session two-driver lap pair from OpenF1 as a fixture.

Closes the Phase 10.2 real-data gate (docs/PHASE_10_2_REAL_DATA_VALIDATION.md).
Run it from a normal network connection, OUTSIDE any live F1 session:
while a session is live (30 min before start -> 30 min after end), OpenF1
rejects ALL unauthenticated requests, historical ones included, with 401.

    cd backend
    python ../scripts/fetch_real_driver_pair.py \\
        --session-key 9161 --driver-a 55 --driver-b 63 \\
        --lap-length-m <official circuit length in metres> \\
        --lap-length-source "<where that number came from>"

Then run:  .venv/bin/python -m pytest tests/test_real_pair_acceptance.py -v

What it does - nothing else:
- uses the existing OpenF1Client (rate limiting, retries, token support);
- verifies the session exists and every returned row carries the
  requested session_key / driver_number (validate_rows_identity) - a
  contaminated or cached response aborts the run instead of being saved;
- selects each driver's lap by the rule in select_reference_lap (explicit
  --lap-a/--lap-b, else the fastest complete non-pit-out lap);
- fetches car_data for exactly that lap's own [date_start, +lap_duration]
  window;
- writes the raw provider rows untouched, plus meta.json recording the
  endpoints, parameters, retrieval time and the lap-length source.

It never edits, fills, or synthesizes a value. --lap-length-m is required
because this project has no circuit geometry to derive it from.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from _common import setup_logging

from app.config import get_settings
from app.providers.openf1.client import OpenF1Client, OpenF1Error
from app.providers.openf1.real_data import select_reference_lap, validate_rows_identity

DEFAULT_OUT = Path(__file__).parent / "fixtures" / "real-openf1-pair"
SCRIPT_VERSION = "2"  # 2: also fetches /v1/location (Phase 10.3)


async def acquire_pair(client, session_key: int, drivers: list[tuple[int, int | None]]) -> dict:
    """Fetch and identity-check everything. Raises on any mismatch/gap.

    `client` needs only an async get(resource, params) -> list[dict], which
    is exactly OpenF1Client.get.
    """
    queries: list[dict] = []

    async def fetch(resource: str, params: dict) -> list[dict]:
        rows = await client.get(resource, params)
        queries.append({"endpoint": f"/v1/{resource}", "params": params, "rows": len(rows)})
        return rows

    sessions = await fetch("sessions", {"session_key": session_key})
    if len(sessions) != 1 or int(sessions[0].get("session_key", -1)) != session_key:
        raise OpenF1Error(f"session_key={session_key}: expected exactly one matching session, "
                          f"got {[s.get('session_key') for s in sessions]}")

    out: dict = {"session": sessions[0], "drivers": {}, "queries": queries}
    for driver, lap_number in drivers:
        laps = await fetch("laps", {"session_key": session_key, "driver_number": driver})
        validate_rows_identity(laps, driver_number=driver, session_key=session_key)
        lap = select_reference_lap(laps, lap_number)
        if lap is None:
            raise OpenF1Error(f"driver {driver}: no complete non-pit-out lap in session")

        start = datetime.fromisoformat(lap["date_start"])
        end = start + timedelta(seconds=float(lap["lap_duration"]))
        # Keys "date>"/"date<", NOT "date>="/"date<=": OpenF1 rebuilds each
        # filter as f"{key}={value}", so "date>" arrives as the inclusive
        # "date>=<ts>" while "date>=" arrives as "date>==<ts>" and silently
        # matches nothing. Same convention as OpenF1Client._bounds.
        car_params = {
            "session_key": session_key, "driver_number": driver,
            "date>": start.isoformat(), "date<": end.isoformat(),
        }
        car = await fetch("car_data", car_params)
        if not car:
            raise OpenF1Error(f"driver {driver} lap {lap['lap_number']}: no car_data in window "
                              f"(query: /v1/car_data {car_params})")
        validate_rows_identity(car, driver_number=driver, session_key=session_key)
        # Phase 10.3: position for the same window, same identity guard and
        # the same parser-verified date>/date< keys.
        location = await fetch("location", dict(car_params))
        if not location:
            raise OpenF1Error(f"driver {driver} lap {lap['lap_number']}: no location in window "
                              f"(query: /v1/location {car_params})")
        validate_rows_identity(location, driver_number=driver, session_key=session_key)
        out["drivers"][str(driver)] = {"lap": lap, "car_data": car, "location": location}

    if len(out["drivers"]) != 2:
        raise OpenF1Error("need two distinct drivers")
    return out


def write_fixture(result: dict, out_dir: Path, lap_length_m: float, lap_length_source: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    driver_keys = list(result["drivers"])
    for d in driver_keys:
        (out_dir / f"driver_{d}_lap.json").write_text(
            json.dumps(result["drivers"][d]["lap"], indent=1))
        (out_dir / f"driver_{d}_car_data.json").write_text(
            json.dumps(result["drivers"][d]["car_data"]))
        (out_dir / f"driver_{d}_location.json").write_text(
            json.dumps(result["drivers"][d]["location"]))
    s = result["session"]
    meta = {
        "kind": "REAL provider data - raw OpenF1 rows, unmodified",
        "provider": "openf1", "base_url": "https://api.openf1.org",
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "script": "scripts/fetch_real_driver_pair.py", "script_version": SCRIPT_VERSION,
        "session_key": s.get("session_key"), "meeting_key": s.get("meeting_key"),
        "session_name": s.get("session_name"), "session_type": s.get("session_type"),
        "circuit_short_name": s.get("circuit_short_name"), "year": s.get("year"),
        "driver_a": int(driver_keys[0]), "driver_b": int(driver_keys[1]),
        "lap_a": result["drivers"][driver_keys[0]]["lap"]["lap_number"],
        "lap_b": result["drivers"][driver_keys[1]]["lap"]["lap_number"],
        "lap_selection_rule": "app.providers.openf1.real_data.select_reference_lap",
        "lap_length_m": lap_length_m, "lap_length_source": lap_length_source,
        "queries": result["queries"],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session-key", type=int, required=True)
    ap.add_argument("--driver-a", type=int, required=True)
    ap.add_argument("--driver-b", type=int, required=True)
    ap.add_argument("--lap-a", type=int, default=None)
    ap.add_argument("--lap-b", type=int, default=None)
    ap.add_argument("--lap-length-m", type=float, required=True)
    ap.add_argument("--lap-length-source", required=True)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    if args.driver_a == args.driver_b:
        ap.error("--driver-a and --driver-b must be different drivers")
    setup_logging()

    client = OpenF1Client(get_settings())
    try:
        result = await acquire_pair(client, args.session_key,
                                    [(args.driver_a, args.lap_a), (args.driver_b, args.lap_b)])
    except OpenF1Error as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        if "401" in str(exc):
            print("Hint: OpenF1 blocks unauthenticated access to ALL data while an F1 "
                  "session is live. Retry outside the live window.", file=sys.stderr)
        return 1
    finally:
        await client.aclose()

    write_fixture(result, args.out, args.lap_length_m, args.lap_length_source)
    for d, v in result["drivers"].items():
        print(f"driver {d}: lap {v['lap']['lap_number']} ({v['lap']['lap_duration']}s), "
              f"{len(v['car_data'])} car_data rows, {len(v['location'])} location rows")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
