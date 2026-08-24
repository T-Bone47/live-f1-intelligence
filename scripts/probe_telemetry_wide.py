"""Probe telemetry mapping failure rates across the whole race."""

import asyncio
import sys

sys.path.insert(0, "backend")

from app.config import get_settings
from app.providers.openf1 import mapping as om
from app.providers.openf1.client import OpenF1Client


async def probe() -> None:
    c = OpenF1Client(get_settings())
    total_fail = 0
    total_rows = 0
    first_err = ""
    for mins in range(55, 60 * 4, 5):  # every 5 min from 12:55 to ~15:30
        start = f"2026-08-23T{12 + mins // 60:02d}:{mins % 60:02d}:00+00:00"
        end_m = mins + 1
        end = f"2026-08-23T{12 + end_m // 60:02d}:{end_m % 60:02d}:00+00:00"
        try:
            rows = await c.car_data_since("11353", start, end)
        except Exception as e:  # noqa: BLE001
            print(f"{start} fetch error {e}")
            continue
        for r in rows:
            total_rows += 1
            try:
                om.safe(om.to_car_sample, r, "openf1:11353", "B")
            except Exception as e:  # noqa: BLE001
                total_fail += 1
                if not first_err:
                    first_err = f"{type(e).__name__}: {str(e)[:200]} row={str(r)[:300]}"
    print(f"car_data sampled rows={total_rows} failures={total_fail}")
    print(first_err or "all mapped")
    await c.aclose()


if __name__ == "__main__":
    asyncio.run(probe())
