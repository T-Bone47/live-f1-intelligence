"""probe_signalr - bounded investigation of the F1 livetiming SignalR Core feed.

Performs ONE negotiate + connect + handshake + subscribe attempt and prints
what happens. No credentials are used unless F1_BEARER_TOKEN is set in env.
This mirrors what any public live-timing client does; no access controls are
bypassed. If a live session is running, a small slice of real frames may be
printed; otherwise only protocol-level facts are reported.

Usage:
    python scripts/probe_signalr.py [--subscribe] [--timeout 20]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

NEGOTIATE_URL = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
WS_URL = "wss://livetiming.formula1.com/signalrcore"
RS = "\x1e"

TOPICS = [
    "Heartbeat", "DriverList", "SessionInfo", "SessionStatus", "TrackStatus",
    "WeatherData", "RaceControlMessages", "LapCount", "TimingData",
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subscribe", action="store_true", help="also connect+subscribe")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args()

    import httpx

    import os

    token = os.environ.get("F1_BEARER_TOKEN") or None
    headers = {"User-Agent": "BestHTTP"}
    async with httpx.AsyncClient(timeout=15) as hc:
        try:
            resp = await hc.post(NEGOTIATE_URL, headers=headers)
        except Exception as exc:  # noqa: BLE001
            print(f"NEGOTIATE FAILED (network): {exc}")
            return 2
        print(f"NEGOTIATE: HTTP {resp.status_code} auth={'yes' if token else 'no'}")
        if resp.status_code != 200:
            print("  -> negotiate refused; direct-feed access NOT confirmed.")
            return 1
        body = resp.json()
        ct = body.get("connectionToken")
        print(f"  connectionToken received: {bool(ct)} (verify-only, not printed)")
        cookie = resp.headers.get("set-cookie", "")
        if not args.subscribe:
            print("VERIFIED: negotiate reachable without auth at this time/date.")
            return 0

    try:
        import websockets
    except ImportError:
        print("websockets package not installed - install backend dep to probe further")
        return 2

    from urllib.parse import quote

    url = (
        f"{WS_URL}?id={quote(ct)}&access_token={quote(token)}"
        if token
        else f"{WS_URL}?id={quote(ct)}"
    )
    try:
        async with websockets.connect(
            url,
            additional_headers={"User-Agent": "BestHTTP", "Cookie": cookie},
            open_timeout=args.timeout,
            close_timeout=5,
        ) as ws:
            await ws.send(json.dumps({"protocol": "json", "version": 1}) + RS)
            ack = await asyncio.wait_for(ws.recv(), timeout=args.timeout)
            print(f"HANDSHAKE ACK: {ack.strip(RS)[:80]}")

            sub = {
                "type": 1,
                "invocationId": "1",
                "target": "Subscribe",
                "arguments": [TOPICS],
            }
            await ws.send(json.dumps(sub) + RS)
            print(f"SUBSCRIBED topics: {len(TOPICS)} (waiting up to {args.timeout}s for frames)")
            got_snapshot = False
            feeds = {}
            deadline = asyncio.get_event_loop().time() + args.timeout
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                for frame in str(msg).split(RS):
                    if not frame.strip():
                        continue
                    try:
                        data = json.loads(frame)
                    except ValueError:
                        continue
                    t = data.get("type")
                    if t == 3 and isinstance(data.get("result"), dict):
                        got_snapshot = True
                        print(f"SNAPSHOT (completion): channels={sorted(data['result'].keys())}")
                    elif t == 1 and data.get("target") == "feed":
                        arg0 = data.get("arguments", [None])[0]
                        feeds[arg0] = feeds.get(arg0, 0) + 1
                    elif t == 6:
                        continue  # keep-alive ping
            print(f"FEED FRAMES by topic: {feeds or 'none'}")
            verdict = "VERIFIED" if (got_snapshot or feeds) else "CONNECTED-BUT-NO-DATA (no live session?)"
            print(f"LIVE FEED STATUS: {verdict}")
            return 0
    except Exception as exc:  # noqa: BLE001
        print(f"CONNECT/SUBSCRIBE FAILED: {type(exc).__name__}: {str(exc)[:200]}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
