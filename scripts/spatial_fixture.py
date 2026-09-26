"""Phase 12B: the real spatial fixture the frontend tests run on.

    cd backend
    python ../scripts/spatial_fixture.py [--measure]

Writes frontend/tests/fixtures/spatial/dutch_gp_states.json from the 2026
Dutch GP recording, through the same store and builders the API serves:

- states_at: spatial_state_v1 at the LAP 2 (red flag), LAP 10, LAP 40 and
  FINAL frames of the committed Phase 11 timeline golden;
- window: spatial_window_v1, 10 s from the LAP 40 frame at a 0.5 s step.

Nothing is edited or synthesized; the documents are the builders' output.
--measure also times the /spatial/window route (TestClient, real recording):
120 s windows at 0.5, 1 and 2 s steps, payload bytes and the median of 10.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)
from spatial_report import NAME, ROOT, SID, find_recording

from app.analysis.timeline import to_canonical_json
from app.spatial.builder import state_doc, window_doc
from app.storage.spatial_store import SpatialStore

TIMELINE = ROOT / "docs" / "timeline" / "session_timeline_v1_dutch_gp_2026.json"
OUT = ROOT / "frontend" / "tests" / "fixtures" / "spatial" / "dutch_gp_states.json"
STATE_FRAMES = (("LAP", 2), ("LAP", 10), ("LAP", 40), ("FINAL", None))


def _frame_at(frames: list[dict], kind: str, lap: int | None) -> datetime:
    f = next(f for f in frames if f["kind"] == kind and (lap is None or f["lap"] == lap))
    return datetime.fromisoformat(f["at"])


def build_fixture(rec: Path) -> dict:
    store = SpatialStore(rec.parent)
    track, index = store.get_track(SID), store.get_index(SID)
    if index is None:
        raise SystemExit(f"{SID}: spatial geometry not validated; no fixture")
    frames = json.loads(TIMELINE.read_text(encoding="utf-8"))["frames"]
    lap40 = _frame_at(frames, "LAP", 40)
    return {
        "provenance": {"source": "scripts/spatial_fixture.py", "recording": NAME,
                       "session_id": SID, "track_id": track["track_id"],
                       "timeline": "docs/timeline/session_timeline_v1_dutch_gp_2026.json"},
        "states_at": [state_doc(index, _frame_at(frames, kind, lap))
                      for kind, lap in STATE_FRAMES],
        "window": window_doc(index, lap40, lap40 + timedelta(seconds=10), 0.5),
    }


def measure(rec: Path) -> None:
    os.environ["RECORDINGS_DIR"] = str(rec.parent)
    from fastapi.testclient import TestClient

    from app.api import HubRegistry, create_app
    from app.config import get_settings
    get_settings.cache_clear()
    client = TestClient(create_app(HubRegistry()))
    frames = json.loads(TIMELINE.read_text(encoding="utf-8"))["frames"]
    t0 = _frame_at(frames, "LAP", 40)
    url = f"/api/v1/sessions/{SID}/spatial/window"
    params = {"from": t0.isoformat(), "to": (t0 + timedelta(seconds=120)).isoformat()}
    client.get(url, params={**params, "step": 2.0})          # warm the store
    for step in (0.5, 1.0, 2.0):
        times, size = [], 0
        for _ in range(10):
            q0 = time.perf_counter()
            r = client.get(url, params={**params, "step": step})
            times.append((time.perf_counter() - q0) * 1000)
            assert r.status_code == 200, r.text
            size = len(r.content)
        print(f"window 120 s at {step:>4} s: {len(r.json()['states'])} states, "
              f"{size / 1e6:.2f} MB, median {statistics.median(times):.0f} ms "
              f"(min {min(times):.0f}, max {max(times):.0f})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true", help="time the window route")
    args = ap.parse_args()
    rec = find_recording()
    if rec is None:
        print("no recording")
        return 2
    body = to_canonical_json(build_fixture(rec))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(body + b"\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(body)} bytes)")
    if args.measure:
        measure(rec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
