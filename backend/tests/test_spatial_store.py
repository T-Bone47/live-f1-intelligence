"""Phase 12A Task 9: spatial caches next to the recording, fail closed."""

from __future__ import annotations

import os
import random
import shutil
import threading

import pytest
from spatial_synth import SID, T0, synth_rows, write_recording

from app.spatial import builder, contract
from app.spatial.circuits import CitedLength
from app.spatial.source import SpatialIdentityError
from app.spatial.state import state_at
from app.storage.spatial_store import (
    INDEX_CACHE,
    TRACK_CACHE,
    SpatialStore,
    read_index,
    write_index,
)

CIRCUITS = {"Synthetic": CitedLength(4000.0, "synthetic test geometry")}


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    return write_recording(tmp_path_factory.mktemp("rec"), synth_rows(laps=22))


@pytest.fixture
def root(tmp_path, pristine):
    dest = tmp_path / pristine.name
    dest.mkdir()
    for name in ("frames.jsonl.zst", "meta.json"):
        shutil.copy2(pristine / name, dest / name)
    return tmp_path


@pytest.fixture
def builds(monkeypatch):
    calls = []
    real = builder.build_spatial

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)
    monkeypatch.setattr(builder, "build_spatial", counting)
    return calls


def _rec(root):
    return next(root.iterdir())


def test_first_request_builds_both_caches_then_serves_from_disk(root, monkeypatch):
    body = SpatialStore(root, CIRCUITS).get_track_bytes(SID)
    rec = _rec(root)
    for name in (TRACK_CACHE, TRACK_CACHE + ".key", INDEX_CACHE, INDEX_CACHE + ".key"):
        assert (rec / name).exists(), name

    def refuse(*_a, **_kw):
        raise AssertionError("must serve from disk")
    monkeypatch.setattr(builder, "build_spatial", refuse)
    fresh = SpatialStore(root, CIRCUITS)
    assert fresh.get_track_bytes(SID) == body
    assert fresh.get_index(SID) is not None


def test_a_stale_key_rebuilds(root, builds, monkeypatch):
    SpatialStore(root, CIRCUITS).get_track_bytes(SID)
    frames = _rec(root) / "frames.jsonl.zst"
    os.utime(frames, ns=(frames.stat().st_atime_ns, frames.stat().st_mtime_ns + 10**9))
    SpatialStore(root, CIRCUITS).get_track_bytes(SID)
    monkeypatch.setattr(contract, "SPATIAL_BUILDER_VERSION", "spatial-builder-9.9.9")
    SpatialStore(root, CIRCUITS).get_track_bytes(SID)
    assert len(builds) == 3


def test_a_corrupted_cache_is_rebuilt_not_served(root, builds):
    store = SpatialStore(root, CIRCUITS)
    body = store.get_track_bytes(SID)
    rec = _rec(root)
    data = (rec / INDEX_CACHE).read_bytes()
    (rec / INDEX_CACHE).write_bytes(data[: len(data) // 2])
    assert SpatialStore(root, CIRCUITS).get_index(SID) is not None
    (rec / TRACK_CACHE).write_bytes(b"{not json")
    assert SpatialStore(root, CIRCUITS).get_track_bytes(SID) == body
    assert len(builds) == 3


def test_index_round_trips_exactly(root, tmp_path):
    index = SpatialStore(root, CIRCUITS).get_index(SID)
    path = tmp_path / "copy.bin"
    write_index(path, index)
    back = read_index(path)
    assert (back.session_id, back.track_id, back.finish_fraction, back.lap_length_m) == \
           (index.session_id, index.track_id, index.finish_fraction, index.lap_length_m)
    assert back.ref_points == index.ref_points and sorted(back.tracks) == sorted(index.tracks)
    assert (back.line_p95_m, back.corner_precision_met) ==            (index.line_p95_m, index.corner_precision_met)
    assert index.line_p95_m is not None
    for d, trk in index.tracks.items():
        other = back.tracks[d]
        for field in ("t", "x", "y", "flag", "confidence", "lap"):
            assert getattr(other, field) == getattr(trk, field)
        assert [repr(v) for v in other.fraction] == [repr(v) for v in trk.fraction]
    rng = random.Random(9)
    for _ in range(50):
        t = T0.timestamp() + rng.uniform(-10.0, 1400.0)
        assert state_at(back, t) == state_at(index, t)


def test_a_recording_of_another_session_fails_closed(tmp_path):
    write_recording(tmp_path, synth_rows(laps=3), sid="openf1:2", name="openf1-2-race")
    with pytest.raises(SpatialIdentityError):
        SpatialStore(tmp_path, CIRCUITS).get_track("openf1:2")


def test_concurrent_first_requests_build_once(root, builds):
    store, out = SpatialStore(root, CIRCUITS), []
    threads = [threading.Thread(target=lambda: out.append(store.get_track_bytes(SID)))
               for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(builds) == 1 and len(out) == 4 and len(set(out)) == 1


def test_unvalidated_track_has_no_index(root):
    store = SpatialStore(root, {})
    assert store.get_track(SID)["status"] == "UNVALIDATED"
    assert store.get_index(SID) is None
    assert not (_rec(root) / INDEX_CACHE).exists()


def test_no_recording_gives_none(tmp_path):
    store = SpatialStore(tmp_path, CIRCUITS)
    assert store.get_track(SID) is None and store.get_track_bytes(SID) is None
    assert store.get_index(SID) is None


def test_the_cache_key_names_the_builder_version_and_the_recording(root):
    """Spec 9: key = "<builder version>|<frames size>|<frames mtime_ns>". The
    track_id also binds the builder version, but the key must say it too, so
    a cache is never judged by its content alone."""
    SpatialStore(root, CIRCUITS).get_track_bytes(SID)
    rec = _rec(root)
    frames = (rec / "frames.jsonl.zst").stat()
    for name in (TRACK_CACHE, INDEX_CACHE):
        key = (rec / (name + ".key")).read_text(encoding="utf-8").split("|")
        assert key[0] == contract.SPATIAL_BUILDER_VERSION
        assert key[-2:] == [str(frames.st_size), str(frames.st_mtime_ns)]


def test_a_changed_citation_rebuilds_the_cache(root):
    """Final review I1: circuits.json is an input. A corrected length (or a
    newly added citation) must never be answered from the old cache."""
    first = SpatialStore(root, CIRCUITS).get_track(SID)
    assert first["circuit"]["lap_length_m"] == 4000.0
    corrected = {"Synthetic": CitedLength(5000.0, "corrected citation")}
    again = SpatialStore(root, corrected).get_track(SID)
    assert again["circuit"]["lap_length_m"] == 5000.0
    assert again["circuit"]["lap_length_source"] == "corrected citation"
    uncited = SpatialStore(root, {}).get_track(SID)
    assert uncited["status"] == "UNVALIDATED"
    assert SpatialStore(root, CIRCUITS).get_track(SID)["status"] == "VALIDATED_MAP_SECTOR"
