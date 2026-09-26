"""GET /api/v1/sessions/{sid}/timeline (Phase 11).

- no hub: built from the session's recording (same function as the golden),
  cached on disk next to it, identity-checked, fail closed;
- hub running: the hub's own lap frames, captured live by the same recorder -
  and for the same race they equal the offline build's LAP frames.
Synthetic race only exercises the mechanics; real data: test_session_timeline_real.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_session_timeline import race

from app.analysis.timeline import (
    BUILDER_VERSION,
    build_timeline,
    build_timeline_from_recording,
    order_for_replay,
    to_canonical_json,
)
from app.api import HubRegistry, create_app
from app.core.enums import ProvenanceClass
from app.core.events import Envelope
from app.ingest.recorder import Recorder
from app.providers.base import Channel, RawItem
from app.realtime.hub import SessionHub

SID = "openf1:1"


def _renamed(envs: list[Envelope], sid: str = SID) -> list[Envelope]:
    out = []
    for e in envs:
        d = json.loads(e.model_dump_json())
        d["session_id"] = sid
        if d["payload"]["model"].get("session_id") is not None:
            d["payload"]["model"]["session_id"] = sid
        out.append(Envelope.model_validate(d))
    return out


def _record(root, envs: list[Envelope], meta_sid: str = SID, name: str = "openf1-1-race"):
    rec = Recorder(root, name)
    for e in envs:
        rec.write(e)
    rec.write_meta(session_payload={"session_id": meta_sid, "provider_session_key": "1"},
                   provider_name="openf1")
    rec.finalize()
    return rec.dir


def _strip_change(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "position_change"} for r in rows]


@pytest.fixture
def app_factory(monkeypatch, tmp_path):
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    def make(registry: HubRegistry | None = None) -> TestClient:
        return TestClient(create_app(registry or HubRegistry()))
    yield make, tmp_path
    get_settings.cache_clear()


def test_timeline_is_built_from_the_sessions_recording(app_factory):
    make, root = app_factory
    rec_dir = _record(root, _renamed(race()))
    r = make().get(f"/api/v1/sessions/{SID}/timeline")
    assert r.status_code == 200
    assert r.headers["x-timeline-contract"] == "session_timeline_v1"
    assert r.content == to_canonical_json(build_timeline_from_recording(rec_dir))
    body = r.json()
    assert body["session"]["session_id"] == SID
    assert [f["kind"] for f in body["frames"]] == ["START", "LAP", "LAP", "LAP", "FINAL"]


def test_timeline_is_cached_next_to_the_recording_and_rebuilt_when_stale(app_factory):
    make, root = app_factory
    rec_dir = _record(root, _renamed(race()))
    first = make().get(f"/api/v1/sessions/{SID}/timeline").content
    cache = rec_dir / "timeline_v1.json"
    key = rec_dir / "timeline_v1.key"
    assert cache.read_bytes() == first and BUILDER_VERSION in key.read_text()
    # a stale cache (other builder version) is rebuilt, never served
    cache.write_bytes(b'{"stale": true}')
    key.write_text("timeline-builder-0.0.0|0|0")
    assert make().get(f"/api/v1/sessions/{SID}/timeline").content == first


def test_no_recording_and_no_hub_is_an_explicit_404(app_factory):
    make, _root = app_factory
    r = make().get(f"/api/v1/sessions/{SID}/timeline")
    assert r.status_code == 404
    assert "no recording" in r.json()["detail"]


def test_a_recording_for_another_session_is_refused(app_factory):
    make, root = app_factory
    # meta claims openf1:1 but every envelope belongs to openf1:2
    _record(root, _renamed(race(), "openf1:2"), meta_sid=SID)
    r = make().get(f"/api/v1/sessions/{SID}/timeline")
    assert r.status_code == 500
    assert "identity" in r.json()["detail"]


def test_invalid_session_id_is_rejected(app_factory):
    make, _root = app_factory
    assert make().get("/api/v1/sessions/bad id/timeline").status_code == 422


async def test_a_running_hub_serves_its_live_frames_equal_to_the_offline_build(app_factory):
    make, _root = app_factory
    envs = _renamed(race())
    hub = SessionHub(session_id=SID)
    ordered, _ = order_for_replay(envs)
    for _at, e in ordered:               # race order, as a live feed delivers it
        await hub.feed(RawItem(channel=Channel.SESSION_META,
                               payload={"__envelope": e.model_dump(mode="json")},
                               source_timestamp=e.source_timestamp,
                               provenance_class=ProvenanceClass(e.provenance_class)))
    registry = HubRegistry()
    registry.register(hub)
    body = make(registry).get(f"/api/v1/sessions/{SID}/timeline").json()
    assert body["source"]["kind"] == "LIVE_HUB"
    live = [f for f in body["frames"] if f["kind"] == "LAP"]
    offline = [f for f in build_timeline(envs, source={"kind": "X"})["frames"]
               if f["kind"] == "LAP"]
    assert [f["lap"] for f in live] == [1, 2, 3]
    for a, b in zip(live, offline, strict=True):
        assert (a["at"], a["phase"], a["track_flag"]) == (b["at"], b["phase"], b["track_flag"])
        assert a["active_battles"] == b["active_battles"]
        # position_change differs only on LAP 1 (live has no START frame before it)
        assert _strip_change(a["rows"]) == _strip_change(b["rows"])
