"""Jolpica-F1 (Ergast-compatible) client.

VERIFIED 2026-08-24:
- https://api.jolpi.ca/ergast/f1/<path>.json works (2026 season = 23 races;
  current driverStandings served).
- Documented limits: 4 req/s burst, 500 req/h unauthenticated; expected to
  tighten. Client defaults conservative (2 rps / 240 rpm).
- NOT live: post-session updates, committed weekly (Monday) at best.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE = "https://api.jolpi.ca/ergast/f1"


class JolpicaError(RuntimeError):
    pass


class _Bucket:
    def __init__(self, rps: float, rpm: float) -> None:
        self._rate = max(rps, 0.05)
        self._tokens = self._rate
        self._cap = max(int(rpm), 1)
        self._rpm = float(self._cap)
        self._t = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                dt = now - self._t
                self._t = now
                self._tokens = min(self._rate, self._tokens + dt * self._rate)
                self._rpm = min(float(self._cap), self._rpm + dt * (self._cap / 60.0))
                if self._tokens >= 1 and self._rpm >= 1:
                    self._tokens -= 1
                    self._rpm -= 1
                    return
                await asyncio.sleep(0.15)


class JolpicaClient:
    def __init__(self, rps: float = 2.0, rpm: float = 240.0, timeout: float = 20.0) -> None:
        self._http = httpx.AsyncClient(timeout=timeout)
        self._bucket = _Bucket(rps, rpm)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{BASE}/{path.lstrip('/')}"
        attempt = 0
        backoff = 1.0
        while True:
            await self._bucket.acquire()
            resp = await self._http.get(url, params=params or {})
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise JolpicaError(f"bad JSON from {url}") from exc
            if resp.status_code == 429 or resp.status_code >= 500:
                attempt += 1
                if attempt > 5:
                    raise JolpicaError(f"{resp.status_code} from {url} after retries")
                delay = float(resp.headers.get("Retry-After") or backoff)
                log.warning("jolpica HTTP %d - retry %d in %.1fs", resp.status_code, attempt, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, 30)
                continue
            raise JolpicaError(f"HTTP {resp.status_code} from {url}: {resp.text[:150]}")

    # typed helpers -----------------------------------------------------------

    async def season_schedule(self, season: str | int) -> list[dict[str, Any]]:
        data = await self.get_json(f"{season}.json", {"limit": 40})
        return (data.get("MRData", {}).get("RaceTable", {}).get("Races")) or []

    async def race_results(self, season: str | int, round_no: int | str,
                           limit: int = 40) -> list[dict[str, Any]]:
        data = await self.get_json(
            f"{season}/{round_no}/results.json", {"limit": limit}
        )
        races = (data.get("MRData", {}).get("RaceTable", {}).get("Races")) or []
        return (races[0].get("Results") or []) if races else []

    async def qualifying_results(self, season: str | int, round_no: int | str,
                                 limit: int = 40) -> list[dict[str, Any]]:
        data = await self.get_json(
            f"{season}/{round_no}/qualifying.json", {"limit": limit}
        )
        races = (data.get("MRData", {}).get("RaceTable", {}).get("Races")) or []
        return (races[0].get("QualifyingResults") or []) if races else []

    async def driver_standings(self, season: str | int, limit: int = 40) -> list[dict[str, Any]]:
        data = await self.get_json(f"{season}/driverStandings.json", {"limit": limit})
        lists = (data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists")) or []
        if not lists:
            return []
        standings = lists[0]
        out = list(standings.get("DriverStandings") or [])
        for entry in out:
            entry["_round"] = standings.get("round")
        return out

    async def constructors_standings(self, season: str | int, limit: int = 40) -> list[dict[str, Any]]:
        data = await self.get_json(f"{season}/constructorStandings.json", {"limit": limit})
        lists = (data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists")) or []
        if not lists:
            return []
        return list(lists[0].get("ConstructorStandings") or [])
