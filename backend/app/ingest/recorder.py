"""Canonical-frame recorder: append-only .jsonl.zst + meta.json.

This IS the replay source of truth. Format documented in
app/providers/replay.py and docs/DATA_PIPELINE.md.
"""

from __future__ import annotations

import io
import json
import logging
import time
from pathlib import Path

from zstandard import ZstdCompressor

from app.core.events import Envelope

log = logging.getLogger(__name__)


class Recorder:
    def __init__(self, recordings_dir: Path, recording_name: str) -> None:
        self.dir = Path(recordings_dir) / recording_name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.frames_path = self.dir / "frames.jsonl.zst"
        self.meta_path = self.dir / "meta.json"
        self._fh = open(self.frames_path, "wb")  # noqa: SIM115 - closed in finalize()
        self._cctx = ZstdCompressor(level=3)
        self._seq = 0
        self.event_types: set[str] = set()

    @property
    def seq(self) -> int:
        return self._seq

    def write(self, envelope: Envelope) -> int:
        """Append one envelope; returns assigned seq."""
        self._seq += 1
        envelope.seq = self._seq
        record = {"seq": self._seq, "envelope": json.loads(envelope.model_dump_json())}
        line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
        self._fh.write(self._cctx.compress(line))
        self.event_types.add(envelope.event_type)
        return self._seq

    def write_meta(
        self,
        session_payload: dict,
        provider_name: str,
        capabilities_notes: list[str] | None = None,
    ) -> None:
        meta = {
            "session": session_payload,
            "provider": provider_name,
            "recorded_at_epoch": time.time(),
            "frames": self._seq,
            "event_types": sorted(self.event_types),
            "format": "f1intel-recording-v1",
            "capabilities_notes": capabilities_notes or [],
        }
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def finalize(self) -> None:
        try:
            self._fh.flush()
        finally:
            self._fh.close()
        log.info("recorder finalized at %s (%d frames)", self.frames_path, self._seq)


_SESSION_KEYS = ("session_id", "provider_session_key", "session_name", "country_code",
                 "status", "date_start", "date_end", "meeting_name", "year",
                 "session_type", "circuit_short_name")


def finalize_interrupted(recording_dir: Path, note: str) -> dict:
    """Write meta.json for a recording whose recorder never did (it died or was
    stopped). Everything is derived from the frames and labelled: the meta says
    `interrupted`, carries the caller's note, and lists per-model-type counts
    and the last source timestamp so the coverage can be judged. Refuses to
    overwrite an existing meta.json."""
    from zstandard import ZstdDecompressor

    rec = Path(recording_dir)
    meta_path = rec / "meta.json"
    if meta_path.exists():
        raise FileExistsError(f"{meta_path} exists; not overwriting a recorder's own meta")
    frames = bad = 0
    event_types: set[str] = set()
    coverage: dict[str, dict] = {}
    session: dict = {}
    provider = None
    with open(rec / "frames.jsonl.zst", "rb") as fh:
        reader = ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        for raw in io.BufferedReader(reader):
            if not raw.strip():
                continue
            try:
                env = json.loads(raw)["envelope"]
            except (ValueError, KeyError):
                bad += 1
                continue
            frames += 1
            event_types.add(env["event_type"])
            model = (env.get("payload") or {}).get("model") or {}
            mtype = model.get("type", "UNKNOWN")
            c = coverage.setdefault(mtype, {"count": 0, "last_source_ts": None})
            c["count"] += 1
            ts = env.get("source_timestamp")
            if ts and (c["last_source_ts"] is None or ts > c["last_source_ts"]):
                c["last_source_ts"] = ts
            if mtype == "SessionInfo" and not session:
                session = {k: model.get(k) for k in _SESSION_KEYS}
                provider = model.get("provider")
    meta = {
        "session": session,
        "provider": provider,
        "recorded_at_epoch": (rec / "frames.jsonl.zst").stat().st_mtime,
        "frames": frames,
        "unreadable_lines": bad,
        "event_types": sorted(event_types),
        "format": "f1intel-recording-v1",
        "capabilities_notes": [],
        "interrupted": True,
        "note": note,
        "coverage": {k: coverage[k] for k in sorted(coverage)},
        "finalized_by": "app.ingest.recorder.finalize_interrupted",
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
