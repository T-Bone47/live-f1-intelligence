"""Orange Cat Blacktop REST client (https://api.ocblacktop.com/v1).

VERIFIED 2026-09-25 against the real API (free-tier key):
- Auth: `x-api-key` header. Responses carry RateLimit headers incl.
  x-ratelimit-remaining-month (free = 7,500/month, 60/min).
- /formula1/events filters by `year=`. `season=` is SILENTLY IGNORED (returns
  all 1,210 events 1950-2027) -> refused here, like OpenF1's `date>=`.
- /formula1/events is paginated ({data, meta.totalPages}); 2023 = 24 events
  incl. Pre-Season Testing and the cancelled Emilia Romagna GP. No round numbers.
- /formula1/events/{id}/sessions/{id}/results and /standings/drivers?year=
  return bare lists.
- live timing, lap times, lap charts, telemetry: HTTP 402
  {"requiredTier": "hobby", "currentTier": "free"}.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE = "https://api.ocblacktop.com/v1"
_REFUSED_PARAMS = {"season": "use `year=`; Blacktop silently ignores `season=`"}


class BlacktopError(RuntimeError):
    pass


class BlacktopTierError(BlacktopError):
    """Endpoint exists but the key's plan does not include it (HTTP 402)."""

    def __init__(self, message: str, required_tier: str | None, current_tier: str | None):
        super().__init__(message)
        self.required_tier = required_tier
        self.current_tier = current_tier


class BlacktopIdentityError(BlacktopError):
    """Response does not describe what was asked for - never used silently."""


class _MinuteWindow:
    """Sliding 60 s window; keeps us under the plan's per-minute ceiling."""

    def __init__(self, rpm: int) -> None:
        self._rpm = max(int(rpm), 1)
        self._stamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._stamps = [t for t in self._stamps if now - t < 60.0]
                if len(self._stamps) < self._rpm:
                    self._stamps.append(now)
                    return
                await asyncio.sleep(max(60.0 - (now - self._stamps[0]), 0.05))


def _int_or_none(raw: str | None) -> int | None:
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


class BlacktopClient:
    def __init__(self, api_key: str, base_url: str = BASE, rpm: int = 50,
                 timeout: float = 20.0, max_retries: int = 4,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise ValueError("Blacktop API key is required")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport,
                                       headers={"x-api-key": api_key})
        self._window = _MinuteWindow(rpm)
        self._max_retries = max_retries
        self.last_rate: dict[str, int | None] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "<redacted>")

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        for bad, why in _REFUSED_PARAMS.items():
            if bad in params:
                raise ValueError(f"query key {bad!r} refused: {why}")
        url = f"{self._base}/{path.lstrip('/')}"
        attempt = 0
        backoff = 1.0
        while True:
            await self._window.acquire()
            resp = await self._http.get(url, params=params)
            self.last_rate = {
                "minute_remaining": _int_or_none(resp.headers.get("x-ratelimit-remaining")),
                "month_remaining": _int_or_none(resp.headers.get("x-ratelimit-remaining-month")),
            }
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise BlacktopError(f"bad JSON from {path}") from exc
            if resp.status_code == 402:
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                raise BlacktopTierError(
                    f"{path}: {body.get('message', 'paid plan required')}",
                    required_tier=body.get("requiredTier"),
                    current_tier=body.get("currentTier"),
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                attempt += 1
                if attempt > self._max_retries:
                    raise BlacktopError(f"HTTP {resp.status_code} from {path} after retries")
                delay = float(resp.headers.get("Retry-After") or backoff)
                log.warning("blacktop HTTP %d - retry %d in %.1fs", resp.status_code,
                            attempt, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, 30.0)
                continue
            raise BlacktopError(
                f"HTTP {resp.status_code} from {path}: {self._redact(resp.text[:200])}")

    # typed helpers -----------------------------------------------------------

    async def events(self, year: int) -> list[dict[str, Any]]:
        """All F1 events of `year` (every page), identity-checked."""
        out: list[dict[str, Any]] = []
        page, total_pages, total = 1, 1, None
        while page <= total_pages:
            body = await self.get_json("/formula1/events", {"year": year, "page": page})
            meta = body.get("meta") or {}
            total_pages = int(meta.get("totalPages") or 1)
            total = meta.get("total", total)
            out.extend(body.get("data") or [])
            page += 1
        wrong = sorted({str(e.get("dateStart"))[:4] for e in out
                        if str(e.get("dateStart"))[:4] != str(year)})
        if wrong:
            raise BlacktopIdentityError(
                f"events?year={year} returned rows dated {', '.join(wrong)}")
        if total is not None and int(total) != len(out):
            raise BlacktopIdentityError(
                f"events?year={year}: meta.total={total} but {len(out)} rows collected")
        return out

    async def event(self, event_id: str) -> dict[str, Any]:
        body = await self.get_json(f"/formula1/events/{event_id}")
        got = body.get("id") if isinstance(body, dict) else None
        if got != event_id:
            raise BlacktopIdentityError(f"event {event_id}: response id {got!r}")
        return body

    async def session_results(self, event_id: str, session_id: str) -> list[dict[str, Any]]:
        body = await self.get_json(f"/formula1/events/{event_id}/sessions/{session_id}/results")
        if not isinstance(body, list):
            raise BlacktopError(f"results {event_id}/{session_id}: expected a list")
        return body

    async def driver_standings(self, year: int) -> list[dict[str, Any]]:
        body = await self.get_json("/formula1/standings/drivers", {"year": year})
        if not isinstance(body, list):
            raise BlacktopError(f"standings/drivers?year={year}: expected a list")
        return body
