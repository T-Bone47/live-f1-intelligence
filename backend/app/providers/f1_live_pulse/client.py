"""RapidAPI "F1 Live Pulse" client - quota-guarded, never retries.

VERIFIED 2026-09-25 with the project key (free plan):
- Base https://f1-live-pulse.p.rapidapi.com, headers x-rapidapi-key /
  x-rapidapi-host. Routes = ROUTES (read from the RapidAPI listing).
- Quota: 20 requests per cycle (~23 days), reported on every response in
  x-ratelimit-requests-{limit,remaining,reset}. At that budget this source
  CANNOT be a live feed (one race needs thousands of polls); it is for
  recording a handful of real fixtures during a live session.
- /trackStatus -> 401 "This endpoint is disabled for your subscription".
- Real shapes seen: /sessionInfo {sessionKey, meetingKey, sessionName,
  sessionStatus, currentLap, trackStatus, ...}; /driverList [{Tla, FullName,
  RacingNumber, TeamName}] (F1 livetiming DriverList casing); /timingData
  {cutOffTime, lines:[{Sectors:[{Value, Segments:[{Status}]}], ...}]}.

Guard: a JSON ledger (no key inside) persists the last-seen remaining count
and reset time across processes. A request is refused BEFORE sending when
remaining <= reserve. 429 is never retried (a retry would spend quota).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE = "https://f1-live-pulse.p.rapidapi.com"
ROUTES = frozenset({
    "sessionInfo", "calendar", "event", "driverList", "timingData", "lapTimes",
    "timingStats", "tyreStints", "teamRadio", "raceControlMessages", "weatherData",
    "trackLimits", "driverPositions", "championshipPrediction", "trackStatus",
    "liveCommentary", "fiaDocuments", "driverStandings", "teamStandings",
})


class LivePulseError(RuntimeError):
    pass


class LivePulseQuotaExhausted(LivePulseError):
    pass


class LivePulseTierError(LivePulseError):
    """Route exists but the plan does not include it."""


def _int(raw: str | None) -> int | None:
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


class LivePulseClient:
    def __init__(self, api_key: str, host: str, ledger_path: Path, base_url: str = BASE,
                 reserve: int = 2, timeout: float = 10.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise ValueError("RapidAPI key is required")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._reserve = max(int(reserve), 0)
        self._ledger_path = Path(ledger_path)
        self._http = httpx.AsyncClient(
            timeout=timeout, transport=transport,
            headers={"x-rapidapi-key": api_key, "x-rapidapi-host": host})
        self.limit: int | None = None
        self.remaining: int | None = None
        self.reset_at: datetime | None = None
        self._load_ledger()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ledger ------------------------------------------------------------------

    def _load_ledger(self) -> None:
        try:
            data = json.loads(self._ledger_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return
        reset = data.get("reset_at_utc")
        self.reset_at = datetime.fromisoformat(reset) if reset else None
        if self.reset_at and self.reset_at <= datetime.now(UTC):
            return  # cycle over: remaining unknown until the next response
        self.limit = data.get("limit")
        self.remaining = data.get("remaining")

    def _save_ledger(self) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._ledger_path.write_text(json.dumps({
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at_utc": self.reset_at.isoformat() if self.reset_at else None,
            "updated_at_utc": datetime.now(UTC).isoformat(),
        }, indent=1), encoding="utf-8")

    def _record(self, resp: httpx.Response) -> None:
        remaining = _int(resp.headers.get("x-ratelimit-requests-remaining"))
        if remaining is None:
            return
        self.remaining = remaining
        self.limit = _int(resp.headers.get("x-ratelimit-requests-limit"))
        reset_s = _int(resp.headers.get("x-ratelimit-requests-reset"))
        self.reset_at = (datetime.now(UTC) + timedelta(seconds=reset_s)
                         if reset_s is not None else None)
        self._save_ledger()

    # requests ----------------------------------------------------------------

    async def get(self, route: str, params: dict[str, Any] | None = None) -> Any:
        if route not in ROUTES:
            raise ValueError(f"unknown F1 Live Pulse route {route!r}; allowed: {sorted(ROUTES)}")
        if self.remaining is not None and self.remaining <= self._reserve:
            raise LivePulseQuotaExhausted(
                f"{self.remaining} requests left (reserve {self._reserve}); "
                f"resets {self.reset_at.isoformat() if self.reset_at else 'unknown'}")
        resp = await self._http.get(f"{self._base}/{route}", params=params or {})
        self._record(resp)
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as exc:
                raise LivePulseError(f"bad JSON from /{route}") from exc
        text = resp.text[:200].replace(self._key, "<redacted>")
        if resp.status_code == 429:
            raise LivePulseQuotaExhausted(f"/{route}: HTTP 429 {text}")
        if resp.status_code == 401 and "disabled for your subscription" in text:
            raise LivePulseTierError(f"/{route}: {text}")
        raise LivePulseError(f"/{route}: HTTP {resp.status_code} {text}")
