"""Async SignalR Core client for livetiming.formula1.com (Phase 1.5).

Connection path VERIFIED 2026-08-24 (negotiate/handshake/subscribe/snapshot).
Incremental feed handling is implemented per documented protocol and marked
ASSUMED until first live capture. The client is DISABLED by default
(SIGNALR_ENABLED=false) and performs no automatic fallback bypassing access
controls: if auth is ever required, set F1_BEARER_TOKEN; if the endpoint
refuses, the client reports failure - it never retries aggressively.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Callable
from urllib.parse import quote

import httpx

from app.providers.signalr import protocol as sp

log = logging.getLogger(__name__)

NEGOTIATE_URL = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
WS_URL = "wss://livetiming.formula1.com/signalrcore"


@dataclass
class FeedMessage:
    topic: str | None
    payload: object          # parsed JSON or raw string for .z topics
    timestamp: str | None


class SignalRClient:
    def __init__(
        self,
        topics: list[str],
        bearer_token: str | None = None,
        idle_timeout_s: float = 45.0,
        max_backoff_s: float = 60.0,
        on_reconnect: Callable[[], None] | None = None,
    ) -> None:
        self._topics = list(topics)
        self._token = bearer_token
        self._idle_timeout = idle_timeout_s
        self._max_backoff = max_backoff_s
        self._on_reconnect = on_reconnect
        self.reconnects = 0

    async def _negotiate(self) -> tuple[str, str]:
        async with httpx.AsyncClient(timeout=15) as hc:
            headers = {"User-Agent": "BestHTTP"}
            resp = await hc.post(NEGOTIATE_URL, headers=headers)
            if resp.status_code != 200:
                raise ConnectionError(f"negotiate refused: HTTP {resp.status_code}")
            ct = resp.json().get("connectionToken")
            if not ct:
                raise ConnectionError("negotiate returned no connectionToken")
            return ct, resp.headers.get("set-cookie", "")

    async def stream(self) -> AsyncIterator[FeedMessage]:
        """Connect and yield FeedMessages forever (supervised reconnect)."""
        import websockets  # lazy: optional dependency path

        backoff = 2.0
        while True:
            try:
                ct, cookie = await self._negotiate()
                url = (
                    f"{WS_URL}?id={quote(ct)}&access_token={quote(self._token)}"
                    if self._token else f"{WS_URL}?id={quote(ct)}"
                )
                headers = {"User-Agent": "BestHTTP", "Cookie": cookie}
                async with websockets.connect(
                    url, additional_headers=headers,
                    open_timeout=15, close_timeout=5,
                ) as ws:
                    await ws.send(sp.handshake_frame())
                    ack = await asyncio.wait_for(ws.recv(), timeout=15)
                    frames = sp.decode_frames(ack)
                    if not frames:
                        raise ConnectionError(f"bad handshake ack: {str(ack)[:80]}")

                    await ws.send(sp.subscribe_frame(self._topics))
                    log.info("signalr subscribed %d topics", len(self._topics))
                    backoff = 2.0
                    if self._on_reconnect:
                        self._on_reconnect()

                    idle = 0.0
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=self._idle_timeout)
                        except asyncio.TimeoutError:
                            # server silent too long: force reconnect+resync
                            log.warning("signalr idle %.0fs - reconnecting", self._idle_timeout)
                            break
                        for frame in sp.decode_frames(raw):
                            kind, data = sp.classify_frame(frame)
                            if kind == "ping":
                                continue
                            if kind == "feed":
                                yield FeedMessage(
                                    topic=data.get("topic"),
                                    payload=data.get("data"),
                                    timestamp=data.get("timestamp"),
                                )
                            # snapshots are handled by the provider on first pass
                            if kind == "snapshot":
                                yield FeedMessage(topic="__snapshot__",
                                                   payload=data, timestamp=None)
                        idle = 0.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.reconnects += 1
                log.warning(
                    "signalr connection lost (%s: %.160s) - retry %.1fs [reconnect #%d]",
                    type(exc).__name__, exc, backoff, self.reconnects,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
