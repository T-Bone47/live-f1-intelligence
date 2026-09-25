"""Blacktop client: HTTP-contract behaviour.

These use httpx.MockTransport - synthetic by design: they pin the client's
own mechanics (auth header, query-key guard, pagination, tier errors, key
redaction). Evidence that the REAL API behaves this way is in the recorded
fixtures (tests/test_blacktop_mapping.py) and docs/DATA_SOURCES.md §2.7.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.blacktop.client import (
    BlacktopClient,
    BlacktopError,
    BlacktopIdentityError,
    BlacktopTierError,
)

KEY = "sk_test_not_a_real_key_0123456789"


def _client(handler) -> BlacktopClient:
    return BlacktopClient(api_key=KEY, transport=httpx.MockTransport(handler), rpm=10_000)


def _event(year: int, n: int) -> dict:
    return {"id": f"ev-{year}-{n}", "name": f"GP {n}", "dateStart": f"{year}-05-{n:02d}",
            "status": "completed", "schedule": []}


async def test_sends_key_in_x_api_key_header_only():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["hdr"] = req.headers.get("x-api-key")
        seen["url"] = str(req.url)
        return httpx.Response(200, json=[])

    c = _client(handler)
    await c.get_json("/formula1/standings/drivers", {"year": 2023})
    await c.aclose()
    assert seen["hdr"] == KEY
    assert KEY not in seen["url"]


async def test_season_query_key_is_refused_because_upstream_silently_ignores_it():
    # VERIFIED 2026-09-25: ?season=2023 returned all 1,210 events (1950-2027)
    # while ?year=2023 returned the 24 events of 2023. A silently ignored
    # filter is the same trap as OpenF1's `date>=`.
    def handler(req):  # pragma: no cover - must never be reached
        raise AssertionError("request must not be sent")

    c = _client(handler)
    with pytest.raises(ValueError, match="year"):
        await c.get_json("/formula1/events", {"season": 2023})
    await c.aclose()


async def test_events_uses_year_and_follows_pagination():
    pages = {
        "1": {"data": [_event(2023, i) for i in range(1, 21)],
              "meta": {"page": 1, "limit": 20, "total": 24, "totalPages": 2}},
        "2": {"data": [_event(2023, i) for i in range(21, 25)],
              "meta": {"page": 2, "limit": 20, "total": 24, "totalPages": 2}},
    }
    params_seen = []

    def handler(req):
        params_seen.append(dict(req.url.params))
        return httpx.Response(200, json=pages[req.url.params.get("page", "1")])

    c = _client(handler)
    events = await c.events(2023)
    await c.aclose()
    assert len(events) == 24
    assert all(p.get("year") == "2023" for p in params_seen)
    assert "season" not in str(params_seen)


async def test_events_rejects_rows_from_another_year():
    # Identity guard: if the filter is ever ignored again, fail loudly
    # instead of mixing seasons.
    def handler(req):
        return httpx.Response(200, json={"data": [_event(2023, 1), _event(2027, 2)],
                                         "meta": {"page": 1, "totalPages": 1}})

    c = _client(handler)
    with pytest.raises(BlacktopIdentityError, match="2027"):
        await c.events(2023)
    await c.aclose()


async def test_events_rejects_short_pagination():
    def handler(req):
        return httpx.Response(200, json={"data": [_event(2023, 1)],
                                         "meta": {"page": 1, "total": 24, "totalPages": 1}})

    c = _client(handler)
    with pytest.raises(BlacktopIdentityError, match="24"):
        await c.events(2023)
    await c.aclose()


async def test_402_raises_tier_error_with_required_tier():
    body = {"message": "This endpoint requires a paid plan", "requiredTier": "hobby",
            "currentTier": "free", "upgradeUrl": "https://ocblacktop.com/api#pricing"}

    c = _client(lambda req: httpx.Response(402, json=body))
    with pytest.raises(BlacktopTierError) as exc:
        await c.get_json("/formula1/live/sessions/x/timing")
    await c.aclose()
    assert exc.value.required_tier == "hobby"
    assert exc.value.current_tier == "free"


async def test_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json=[{"ok": 1}])

    c = _client(handler)
    assert await c.get_json("/formula1/standings/drivers", {"year": 2023}) == [{"ok": 1}]
    await c.aclose()
    assert calls["n"] == 2


async def test_errors_never_leak_the_key():
    c = _client(lambda req: httpx.Response(401, text=f"bad key {KEY}"))
    with pytest.raises(BlacktopError) as exc:
        await c.get_json("/formula1/drivers")
    await c.aclose()
    assert KEY not in str(exc.value)
    assert "<redacted>" in str(exc.value)


async def test_records_rate_limit_headers():
    hdrs = {"x-ratelimit-remaining": "57", "x-ratelimit-remaining-month": "7497"}
    c = _client(lambda req: httpx.Response(200, headers=hdrs, json=[]))
    await c.get_json("/formula1/drivers")
    await c.aclose()
    assert c.last_rate == {"minute_remaining": 57, "month_remaining": 7497}


def test_empty_key_is_refused():
    with pytest.raises(ValueError):
        BlacktopClient(api_key="")
