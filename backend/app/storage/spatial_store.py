"""Phase 12A spatial store: track reference and sample index, cached next to
the session's recording (the replay source of truth), like timeline_v1:

    <recording>/track_reference_v1.json   canonical bytes
    <recording>/spatial_samples_v1.bin    classified samples (validated tracks only)
    <file>.key                            "<builder version>|<frames size>|<frames mtime_ns>"

A cache whose key does not match - or that cannot be read back whole - is
rebuilt, never served. Every served document is validated and identity-checked
against the requested session (fail closed).
"""

from __future__ import annotations

import json
import sys
import threading
from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import app.spatial.builder as _builder
import app.spatial.contract as _contract
from app.analysis.timeline import to_canonical_json
from app.spatial.circuits import CitedLength
from app.spatial.source import SpatialIdentityError, load_inputs
from app.spatial.state import DriverTrack, SpatialIndex
from app.storage.timeline_store import index_recordings

TRACK_CACHE = "track_reference_v1.json"
INDEX_CACHE = "spatial_samples_v1.bin"
KEY_SUFFIX = ".key"
INDEX_FORMAT = "spatial-samples-v1"
_FIELDS = (("t", "d"), ("x", "d"), ("y", "d"), ("fraction", "d"),
           ("flag", "b"), ("confidence", "b"), ("lap", "h"))


def write_index(path: Path, index: SpatialIndex) -> None:
    drivers = sorted(index.tracks)
    header = {"format": INDEX_FORMAT, "byteorder": sys.byteorder,
              "session_id": index.session_id, "track_id": index.track_id,
              "finish_fraction": index.finish_fraction, "lap_length_m": index.lap_length_m,
              "ref_points": [list(p) for p in index.ref_points],
              "drivers": [{"driver": d, "n": len(index.tracks[d].t)} for d in drivers]}
    with open(path, "wb") as fh:
        fh.write(json.dumps(header, separators=(",", ":")).encode() + b"\n")
        for d in drivers:
            fh.writelines(getattr(index.tracks[d], name).tobytes() for name, _code in _FIELDS)


def read_index(path: Path) -> SpatialIndex:
    """Raises ValueError on any format, byte-order or length mismatch."""
    data = Path(path).read_bytes()
    head, _, body = data.partition(b"\n")
    header = json.loads(head)
    if header.get("format") != INDEX_FORMAT or header.get("byteorder") != sys.byteorder:
        raise ValueError("spatial index: unknown format or byte order")
    tracks: dict[int, DriverTrack] = {}
    pos = 0
    for entry in header["drivers"]:
        n, arrays = int(entry["n"]), {}
        for name, code in _FIELDS:
            arr = array(code)
            size = n * arr.itemsize
            if pos + size > len(body):
                raise ValueError("spatial index: truncated")
            arr.frombytes(body[pos:pos + size])
            pos += size
            arrays[name] = arr
        tracks[int(entry["driver"])] = DriverTrack(**arrays)
    if pos != len(body):
        raise ValueError("spatial index: trailing bytes")
    return SpatialIndex(session_id=header["session_id"], track_id=header["track_id"],
                        ref_points=tuple((float(x), float(y)) for x, y in header["ref_points"]),
                        finish_fraction=float(header["finish_fraction"]),
                        lap_length_m=header["lap_length_m"], tracks=tracks)


@dataclass
class _Entry:
    key: str
    doc: dict
    body: bytes
    index: SpatialIndex | None


class SpatialStore:
    def __init__(self, recordings_dir: Path,
                 circuits: Mapping[str, CitedLength] | None = None) -> None:
        self.root = Path(recordings_dir)
        self.circuits = circuits
        self._memory: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(rec: Path) -> str:
        st = (rec / "frames.jsonl.zst").stat()
        return f"{_contract.SPATIAL_BUILDER_VERSION}|{st.st_size}|{st.st_mtime_ns}"

    @staticmethod
    def _keyed(path: Path, key: str) -> bool:
        key_file = path.with_name(path.name + KEY_SUFFIX)
        return path.exists() and key_file.exists() and \
            key_file.read_text(encoding="utf-8").strip() == key

    @staticmethod
    def _check_identity(doc: dict, session_id: str) -> None:
        found = (doc.get("session") or {}).get("session_id")
        if found != session_id:
            raise SpatialIdentityError(f"spatial cache holds session {found!r}, not {session_id!r}")

    def _from_disk(self, rec: Path, session_id: str, key: str) -> _Entry | None:
        track_path, index_path = rec / TRACK_CACHE, rec / INDEX_CACHE
        if not self._keyed(track_path, key):
            return None
        try:
            body = track_path.read_bytes()
            doc = json.loads(body)
            _contract.validate_track(doc)
        except (OSError, ValueError):
            return None                      # unreadable or invalid: rebuild
        self._check_identity(doc, session_id)
        index = None
        if doc["status"] == "VALIDATED_MAP_SECTOR":
            if not self._keyed(index_path, key):
                return None
            try:
                index = read_index(index_path)
            except (OSError, ValueError, KeyError):
                return None
            if (index.session_id, index.track_id) != (session_id, doc["track_id"]):
                return None
        return _Entry(key, doc, body, index)

    def _build(self, rec: Path, session_id: str, key: str) -> _Entry:
        doc, index = _builder.build_spatial(load_inputs(rec, session_id), self.circuits)
        self._check_identity(doc, session_id)
        body = to_canonical_json(doc)
        (rec / TRACK_CACHE).write_bytes(body)
        if index is not None:
            write_index(rec / INDEX_CACHE, index)
            (rec / (INDEX_CACHE + KEY_SUFFIX)).write_text(key, encoding="utf-8")
        (rec / (TRACK_CACHE + KEY_SUFFIX)).write_text(key, encoding="utf-8")  # keys last
        return _Entry(key, doc, body, index)

    def _entry(self, session_id: str) -> _Entry | None:
        rec = index_recordings(self.root).get(session_id)
        if rec is None:
            return None
        key = self._key(rec)
        with self._lock:
            hit = self._memory.get(session_id)
            if hit is not None and hit.key == key:
                return hit
            entry = self._from_disk(rec, session_id, key) or self._build(rec, session_id, key)
            self._memory[session_id] = entry
            return entry

    def get_track(self, session_id: str) -> dict | None:
        entry = self._entry(session_id)
        return None if entry is None else entry.doc

    def get_track_bytes(self, session_id: str) -> bytes | None:
        entry = self._entry(session_id)
        return None if entry is None else entry.body

    def get_index(self, session_id: str) -> SpatialIndex | None:
        entry = self._entry(session_id)
        return None if entry is None else entry.index
