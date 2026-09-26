"""Timeline store (Phase 11): session_timeline_v1 for stored sessions.

A stored session's timeline is built from its recording (the replay source of
truth) by app.analysis.timeline and cached next to it:

    <recording>/timeline_v1.json   canonical bytes
    <recording>/timeline_v1.key    "<builder version>|<frames size>|<frames mtime_ns>"

A cache whose key does not match the current builder and recording is rebuilt,
never served. Every served timeline is validated and identity-checked against
the requested session id (fail closed).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.analysis.timeline import (
    BUILDER_VERSION,
    TimelineContractError,
    build_timeline_from_recording,
    to_canonical_json,
    validate_timeline,
)

CACHE_NAME = "timeline_v1.json"
KEY_NAME = "timeline_v1.key"


class TimelineIdentityError(TimelineContractError):
    """The recording's data belongs to another session."""


def recording_session_id(meta: dict) -> str | None:
    s = meta.get("session") or {}
    if s.get("session_id"):
        return str(s["session_id"])
    if meta.get("provider") and s.get("provider_session_key"):
        return f"{meta['provider']}:{s['provider_session_key']}"
    return None


def index_recordings(root: Path) -> dict[str, Path]:
    """{session_id: recording dir} for complete recordings (meta.json present)
    up to two levels below `root`. First match in sorted path order wins."""
    out: dict[str, Path] = {}
    root = Path(root)
    if not root.exists():
        return out
    for meta_path in sorted([*root.glob("*/meta.json"), *root.glob("*/*/meta.json")]):
        if not (meta_path.parent / "frames.jsonl.zst").exists():
            continue
        try:
            sid = recording_session_id(json.loads(meta_path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            continue
        if sid and sid not in out:
            out[sid] = meta_path.parent
    return out


class TimelineStore:
    def __init__(self, recordings_dir: Path) -> None:
        self.root = Path(recordings_dir)
        self._memory: dict[str, tuple[str, bytes]] = {}
        self._lock = threading.Lock()

    def recording_for(self, session_id: str) -> Path | None:
        return index_recordings(self.root).get(session_id)

    @staticmethod
    def _key(rec: Path) -> str:
        st = (rec / "frames.jsonl.zst").stat()
        return f"{BUILDER_VERSION}|{st.st_size}|{st.st_mtime_ns}"

    def get_bytes(self, session_id: str) -> bytes | None:
        """Canonical timeline bytes, or None when the session has no recording.
        Raises TimelineContractError / TimelineIdentityError (fail closed)."""
        rec = self.recording_for(session_id)
        if rec is None:
            return None
        key = self._key(rec)
        with self._lock:
            hit = self._memory.get(session_id)
            if hit and hit[0] == key:
                return hit[1]
            cache, key_file = rec / CACHE_NAME, rec / KEY_NAME
            body = None
            if cache.exists() and key_file.exists() and \
                    key_file.read_text(encoding="utf-8").strip() == key:
                body = cache.read_bytes()
                timeline = json.loads(body)
            else:
                timeline = build_timeline_from_recording(rec)
            validate_timeline(timeline)
            found = (timeline.get("session") or {}).get("session_id")
            if found != session_id:
                raise TimelineIdentityError(
                    f"identity check failed: recording {rec.name} holds session "
                    f"{found!r}, not {session_id!r}")
            if body is None:
                body = to_canonical_json(timeline)
                cache.write_bytes(body)
                key_file.write_text(key, encoding="utf-8")
            self._memory[session_id] = (key, body)
            return body
