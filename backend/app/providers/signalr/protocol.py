"""SignalR Core protocol primitives for the F1 livetiming feed.

VERIFIED live on 2026-08-24 against livetiming.formula1.com/signalrcore:
- negotiate POST returns 200 + connectionToken WITHOUT auth
- WSS connect, handshake `{"protocol":"json","version":1}` -> ACK `{}`
- Subscribe -> type-3 completion SNAPSHOT listing subscribed channels

ASSUMED (documented across public clients, not yet captured by us):
- incremental type-1 invocations targeting "feed" with [topic, data, ts]
- CarData.z / Position.z deflate-compressed CSV line formats

Everything here is pure/offline-testable. No telemetry is fabricated.
"""

from __future__ import annotations

import json
import zlib

RS = "\x1e"  # SignalR text-protocol record separator


def encode_frame(obj: dict) -> str:
    return json.dumps(obj) + RS


def handshake_frame() -> str:
    return encode_frame({"protocol": "json", "version": 1})


def subscribe_frame(topics: list[str], invocation_id: str = "1") -> str:
    return encode_frame({
        "type": 1,
        "invocationId": invocation_id,
        "target": "Subscribe",
        "arguments": [topics],
    })


def decode_frames(payload: str | bytes) -> list[dict]:
    """Split a transport chunk into JSON frames; skips pings/garbage safely."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    out: list[dict] = []
    for piece in payload.split(RS):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(json.loads(piece))
        except ValueError:
            continue  # malformed frame: ignored, never fatal
    return out


def classify_frame(frame: dict) -> tuple[str, dict]:
    """Return (kind, data) where kind in snapshot|feed|ping|other."""
    t = frame.get("type")
    if t == 3:
        return ("snapshot", frame.get("result") or {})
    if t == 1 and frame.get("target") == "feed":
        args = frame.get("arguments") or []
        topic = args[0] if args else None
        return ("feed", {"topic": topic, "data": args[1] if len(args) > 1 else None,
                          "timestamp": args[2] if len(args) > 2 else None})
    if t == 6:
        return ("ping", {})
    return ("other", {})


def _inflate(blob: bytes) -> str | None:
    """Try zlib then raw-deflate (feed uses one of them; verified on capture)."""
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(blob, wbits).decode("utf-8", errors="replace")
        except zlib.error:
            continue
    return None


def parse_car_data_z(blob: bytes) -> list[dict]:
    """Decompress CarData.z -> rows {utc, rpm, speed_kph, gear, throttle_pct,
    brake_pct, drs}.

    ASSUMED format until first capture: deflate blob; lines of
    `<utc> <rpm> <speed> <nGear> <throttle> <brake> <drs>` grouped per car.
    Malformed lines are skipped silently (never fabricated).
    """
    text = _inflate(blob)
    if text is None:
        return []
    rows: list[dict] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) != 7:
            continue
        try:
            rows.append({
                "utc": parts[0],
                "rpm": int(float(parts[1])),
                "speed_kph": int(float(parts[2])),
                "gear": int(float(parts[3])),
                "throttle_pct": float(parts[4]),
                "brake_pct": float(parts[5]),
                "drs": int(float(parts[6])),
            })
        except ValueError:
            continue
    return rows


def parse_position_z(blob: bytes) -> list[dict]:
    """Decompress Position.z -> rows {utc, x, y, z}. Same caveats as above."""
    text = _inflate(blob)
    if text is None:
        return []
    rows: list[dict] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) != 4:
            continue
        try:
            rows.append({
                "utc": parts[0],
                "x": float(parts[1]),
                "y": float(parts[2]),
                "z": float(parts[3]),
            })
        except ValueError:
            continue
    return rows
