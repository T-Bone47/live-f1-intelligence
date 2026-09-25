"""RapidAPI F1 Live Pulse client: quota guard mechanics.

Synthetic by design (httpx.MockTransport): these pin the guard, not F1 facts.
Real behaviour it encodes, VERIFIED 2026-09-25 with the project key:
- free plan = 20 requests per cycle; headers x-ratelimit-requests-limit /
  -remaining / -reset (seconds to reset, ~23 days);
- unknown paths answer 404 "Endpoint '/x' does not exist";
- /trackStatus answers 401 "This endpoint is disabled for your subscription".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.providers.f1_live_pulse.client import (
    ROUTES,
    LivePulseClient,
    LivePulseError,
    LivePulseQuotaExhausted,
    LivePulseTierError,
)

KEY = "rapid_test_key_not_real_abcdef"
HOST = "f1-live-pulse.p.rapidapi.com"


def _hdrs(remaining: int, reset_s: int = 1_997_945) -> dict:
    return {"x-ratelimit-requests-limit": "20",
            "x-ratelimit-requests-remaining": str(remaining),
            "x-ratelimit-requests-reset": str(reset_s)}


def _client(handler, tmp_path, reserve=2) -> LivePulseClient:
    return LivePulseClient(api_key=KEY, host=HOST, reserve=reserve,
                           ledger_path=tmp_path / "ledger.json",
                           transport=httpx.MockTransport(handler))


def test_verified_route_list_is_exact():
    assert ROUTES == {
        "sessionInfo", "calendar", "event", "driverList", "timingData", "lapTimes",
        "timingStats", "tyreStints", "teamRadio", "raceControlMessages", "weatherData",
        "trackLimits", "driverPositions", "championshipPrediction", "trackStatus",
        "liveCommentary", "fiaDocuments", "driverStandings", "teamStandings",
    }


async def test_unknown_route_is_refused_without_spending_quota(tmp_path):
    def handler(req):  # pragma: no cover
        raise AssertionError("must not send")

    c = _client(handler, tmp_path)
    with pytest.raises(ValueError, match="drivers"):
        await c.get("drivers")
    await c.aclose()


async def test_sends_rapidapi_headers_and_records_quota(tmp_path):
    seen = {}

    def handler(req):
        seen.update(key=req.headers.get("x-rapidapi-key"), host=req.headers.get("x-rapidapi-host"),
                    url=str(req.url))
        return httpx.Response(200, headers=_hdrs(14), json={"sessionKey": 11372})

    c = _client(handler, tmp_path)
    assert await c.get("sessionInfo") == {"sessionKey": 11372}
    await c.aclose()
    assert seen["key"] == KEY and seen["host"] == HOST
    assert seen["url"].endswith("/sessionInfo") and KEY not in seen["url"]
    assert c.remaining == 14
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["remaining"] == 14 and ledger["limit"] == 20
    assert KEY not in (tmp_path / "ledger.json").read_text()


async def test_reserve_blocks_before_sending_and_survives_restart(tmp_path):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, headers=_hdrs(2), json=[])

    c = _client(handler, tmp_path, reserve=2)
    await c.get("driverList")  # remaining now 2 == reserve
    with pytest.raises(LivePulseQuotaExhausted):
        await c.get("driverList")
    await c.aclose()
    # a new process reads the ledger and still refuses
    c2 = _client(handler, tmp_path, reserve=2)
    with pytest.raises(LivePulseQuotaExhausted):
        await c2.get("timingData")
    await c2.aclose()
    assert calls["n"] == 1


async def test_ledger_expires_after_reset(tmp_path):
    past = datetime.now(UTC) - timedelta(seconds=5)
    (tmp_path / "ledger.json").write_text(json.dumps(
        {"limit": 20, "remaining": 0, "reset_at_utc": past.isoformat()}))

    c = _client(lambda req: httpx.Response(200, headers=_hdrs(19), json=[]), tmp_path)
    await c.get("calendar")
    await c.aclose()
    assert c.remaining == 19


async def test_429_is_not_retried(tmp_path):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, headers=_hdrs(0), json={"message": "quota"})

    c = _client(handler, tmp_path)
    with pytest.raises(LivePulseQuotaExhausted):
        await c.get("lapTimes", {"tla": "SAI"})
    await c.aclose()
    assert calls["n"] == 1


async def test_disabled_endpoint_raises_tier_error(tmp_path):
    body = {"message": "This endpoint is disabled for your subscription"}
    c = _client(lambda req: httpx.Response(401, headers=_hdrs(10), json=body), tmp_path)
    with pytest.raises(LivePulseTierError):
        await c.get("trackStatus")
    await c.aclose()
    assert c.remaining == 10  # quota still tracked on failures


async def test_errors_never_leak_the_key(tmp_path):
    c = _client(lambda req: httpx.Response(403, text=f"key {KEY} blocked"), tmp_path)
    with pytest.raises(LivePulseError) as exc:
        await c.get("weatherData")
    await c.aclose()
    assert KEY not in str(exc.value)


def test_empty_key_is_refused(tmp_path):
    with pytest.raises(ValueError):
        LivePulseClient(api_key="", host=HOST, ledger_path=tmp_path / "l.json")
