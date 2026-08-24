"""Canonical-frame recorder: append-only .jsonl.zst + meta.json.

This IS the replay source of truth. Format documented in
app/providers/replay.py and docs/DATA_PIPELINE.md.
"""

from __future__ import annotations

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
