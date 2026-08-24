"""HTTP client for the OpenF1 REST API.

Behavior VERIFIED empirically against api.openf1.org on 2026-08-23:
- GET /v1/<resource> returns a JSON array (never wrapped in an envelope).
- Filters are query params; comparison operators are embedded in the key,
  e.g. `date>2026-08-23T13:00:00` or `lap_number<=3`.
- The `year=` filter returned {"detail":"No results found."} for 2025 AND 2026
  even though 2026 data exists -> do NOT rely on it; use meeting/session keys.
- `session_key=latest` resolves to the most recent session.
- During live sessions the public API restricts access to authenticated
  users (sponsor tier). Outside the live window data is free.
- Free tier limits: ~3 req/s and ~30 req/min. This client enforces both with
  a token bucket and backs off on HTTP 429 / 5xx honoring Retry-After.

All timestamps upstream are ISO-8601 with explicit UTC offset.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import Settings

log = logging.getLogger(__name__)


class OpenF1Error(RuntimeError):
    pass


class RateLimited(OpenF1Error):
    pass


class _TokenBucket:
    """Dual-limit token bucket: per-second burst + per-minute sustained."""

    def __init__(self, rps: float, rpm: float) -> None:
        self._rps_rate = max(rps, 0.05)
        self._rps_tokens = self._rps_rate
        self._rpm_capacity = max(int(rpm), 1)
        self._rpm_tokens = float(self._rpm_capacity)
        self._t_last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._t_last
                self._t_last = now
                self._rps_tokens = min(self._rps_rate, self._rps_tokens + elapsed * self._rps_rate)
                # minute bucket refills continuously across a 60s horizon
                self._rpm_tokens = min(
                    float(self._rpm_capacity), self._rpm_tokens + elapsed * (self._rpm_capacity / 60.0)
                )
                if self._rps_tokens >= 1 and self._rpm_tokens >= 1:
                    self._rps_tokens -= 1
                    self._rpm_tokens -= 1
                    return
                await asyncio.sleep(0.15)


class OpenF1Client:
    def __init__(self, settings: Settings) -> None:
        headers = {"Accept": "application/json"}
        if settings.openf1_api_token:
            headers["Authorization"] = f"Bearer {settings.openf1_api_token}"
        self._client = httpx.AsyncClient(
            base_url=settings.openf1_base_url,
            headers=headers,
            timeout=httpx.Timeout(20.0),
        )
        self._bucket = _TokenBucket(settings.openf1_rate_limit_rps, settings.openf1_rate_limit_rpm)
        self.reconnect_count = 0  # transport-level retries that actually re-sent

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, resource: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """GET /v1/<resource>. Returns [] when API answers 'No results found'."""
        url = f"/v1/{resource.lstrip('/')}"
        attempt = 0
        backoff = 1.0
        while True:
            await self._bucket.acquire()
            try:
                resp = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                attempt += 1
                self.reconnect_count += 1
                if attempt > 5:
                    raise OpenF1Error(f"network failure after {attempt} attempts: {exc}") from exc
                log.warning("network error (%s), retry %d in %.1fs", exc, attempt, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
                continue

            if resp.status_code == 200 or resp.status_code == 404:
                # VERIFIED upstream quirk: empty result sets may arrive as 200
                # {"detail":"No results found."} OR as HTTP 404 with same body.
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise OpenF1Error(f"malformed JSON from {url}: {exc}") from exc
                if isinstance(data, dict) and data.get("detail") == "No results found.":
                    return []
                if resp.status_code == 404:
                    raise OpenF1Error(f"HTTP 404 from {url}: {str(data)[:200]}")
                if not isinstance(data, list):
                    raise OpenF1Error(f"unexpected response shape from {url}: {type(data)!r}")
                return data

            if resp.status_code in (429,) or resp.status_code >= 500:
                attempt += 1
                self.reconnect_count += 1
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else backoff
                if attempt > 6:
                    raise RateLimited(f"{resp.status_code} from {url} after {attempt} attempts")
                log.warning("HTTP %d from %s - retry %d in %.1fs", resp.status_code, url, attempt, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2.0, 60.0)
                continue

            raise OpenF1Error(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")

    # Typed convenience wrappers (verified endpoints only).

    async def sessions_latest(self) -> list[dict[str, Any]]:
        return await self.get("sessions", {"session_key": "latest"})

    async def sessions_for_meeting(self, meeting_key: int | str) -> list[dict[str, Any]]:
        return await self.get("sessions", {"meeting_key": meeting_key})

    async def meetings(self, meeting_key: int | str | None = None, year: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if meeting_key is not None:
            params["meeting_key"] = meeting_key
        if year is not None:
            params["year"] = year  # NOTE: verified flaky upstream; caller must handle []
        return await self.get("meetings", params)

    async def drivers(self, session_key: int | str) -> list[dict[str, Any]]:
        return await self.get("drivers", {"session_key": session_key})

    async def laps_since(
        self, session_key: int | str, iso_cursor: str, iso_until: str | None = None
    ) -> list[dict[str, Any]]:
        # VERIFIED: the laps endpoint filters on `date_start` (its timestamp
        # field), not `date` - `date>` returns empty results.
        params: dict[str, Any] = {"session_key": session_key, "date_start>": iso_cursor}
        if iso_until:
            params["date_start<"] = iso_until
        return await self.get("laps", params)

    async def car_data_since(
        self, session_key: int | str, iso_cursor: str, iso_until: str | None = None
    ) -> list[dict[str, Any]]:
        return await self.get("car_data", self._bounds(session_key, iso_cursor, iso_until))

    async def location_since(
        self, session_key: int | str, iso_cursor: str, iso_until: str | None = None
    ) -> list[dict[str, Any]]:
        return await self.get("location", self._bounds(session_key, iso_cursor, iso_until))

    async def stints(self, session_key: int | str) -> list[dict[str, Any]]:
        return await self.get("stints", {"session_key": session_key})

    async def pits_since(
        self, session_key: int | str, iso_cursor: str | None, iso_until: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"session_key": session_key}
        if iso_cursor:
            params["date>"] = iso_cursor
        if iso_until:
            params["date<"] = iso_until
        return await self.get("pit", params)

    async def weather_since(
        self, session_key: int | str, iso_cursor: str, iso_until: str | None = None
    ) -> list[dict[str, Any]]:
        return await self.get("weather", self._bounds(session_key, iso_cursor, iso_until))

    async def race_control_since(
        self, session_key: int | str, iso_cursor: str, iso_until: str | None = None
    ) -> list[dict[str, Any]]:
        return await self.get("race_control", self._bounds(session_key, iso_cursor, iso_until))

    async def positions_since(
        self, session_key: int | str, iso_cursor: str, iso_until: str | None = None
    ) -> list[dict[str, Any]]:
        return await self.get("position", self._bounds(session_key, iso_cursor, iso_until))

    async def intervals_since(
        self, session_key: int | str, iso_cursor: str, iso_until: str | None = None
    ) -> list[dict[str, Any]]:
        return await self.get("intervals", self._bounds(session_key, iso_cursor, iso_until))

    @staticmethod
    def _bounds(session_key: Any, iso_cursor: str, iso_until: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"session_key": session_key, "date>": iso_cursor}
        if iso_until:
            params["date<"] = iso_until
        return params
