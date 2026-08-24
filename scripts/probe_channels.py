"""Diagnostic probe: fetch small windows from every OpenF1 channel and count
normalization failures. Developer tool, not production code."""

import asyncio
import sys

sys.path.insert(0, "backend")

from app.config import get_settings
from app.providers.openf1 import mapping as om
from app.providers.openf1.client import OpenF1Client


async def probe() -> None:
    c = OpenF1Client(get_settings())
    tests = [
        (
            "car_data",
            lambda: c.car_data_since(
                "11353", "2026-08-23T13:03:28+00:00", "2026-08-23T13:04:28+00:00"
            ),
            om.to_car_sample,
        ),
        (
            "location",
            lambda: c.location_since(
                "11353", "2026-08-23T13:03:28+00:00", "2026-08-23T13:04:28+00:00"
            ),
            om.to_location_sample,
        ),
        (
            "intervals",
            lambda: c.intervals_since(
                "11353", "2026-08-23T13:03:35+00:00", "2026-08-23T13:13:35+00:00"
            ),
            om.to_interval,
        ),
        (
            "position",
            lambda: c.positions_since(
                "11353", "2026-08-23T12:06:00+00:00", "2026-08-23T15:30:00+00:00"
            ),
            om.to_position,
        ),
        (
            "pit",
            lambda: c.pits_since(
                "11353", "2026-08-23T12:00:00+00:00", "2026-08-23T15:30:00+00:00"
            ),
            om.to_pit_stop,
        ),
        (
            "race_control",
            lambda: c.race_control_since(
                "11353", "2026-08-23T12:00:00+00:00", "2026-08-23T15:30:00+00:00"
            ),
            om.to_rcm,
        ),
    ]
    for name, fetch, mapper in tests:
        rows = await fetch()
        fails = 0
        first_err = ""
        for r in rows:
            try:
                om.safe(mapper, r, "openf1:11353", "B")
            except Exception as e:  # noqa: BLE001
                fails += 1
                if not first_err:
                    first_err = f"{type(e).__name__}: {str(e)[:140]} | row={str(r)[:140]}"
        suffix = first_err if first_err else "OK"
        print(f"{name:<14} rows={len(rows):<6} map_failures={fails} {suffix}")
    await c.aclose()


if __name__ == "__main__":
    asyncio.run(probe())
