"""Phase 12C: the real evidence/telemetry fixture the frontend tests run on.

    cd backend
    python ../scripts/evidence_fixture.py [--measure]

Writes frontend/tests/fixtures/evidence/dutch_gp_pair.json from the 2026
Dutch GP recording, through the API routes themselves (TestClient, recording
source, no database):

- pair: the overall fastest eligible lap and the fastest eligible lap of
  another driver (timed, car telemetry, lap >= 2, not pit-out, not deleted);
- evidence: evidence_v1 for that pair (lap length cited in circuits.json);
- evidence_spatial: evidence_spatial_v1 for the same request;
- catalog: /laps for the pair's two drivers (every lap, as served);
- recorded_session: the /sessions entry of the recording;
- telemetry: driver A, RAW, 120 s centred on the LAP 40 frame;
- trace: spatial_trace_v1 for driver A over the same 120 s.

Nothing is edited or synthesized. --measure times the recording store (cold
build, warm load) and the routes (median of 15 warm requests).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timedelta

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)
from spatial_report import NAME, ROOT, SID, find_recording

from app.analysis.timeline import to_canonical_json

TIMELINE = ROOT / "docs" / "timeline" / "session_timeline_v1_dutch_gp_2026.json"
CIRCUITS = ROOT / "backend" / "app" / "spatial" / "circuits.json"
OUT = ROOT / "frontend" / "tests" / "fixtures" / "evidence" / "dutch_gp_pair.json"
TELEMETRY_FIELDS = "speed,throttle,brake,gear,rpm,drs"
HALF_WINDOW_S = 60.0


def pick_pair(catalog: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    """Same rule as backend/tests/test_recording_real.py::pick_pair."""
    eligible = sorted(
        (lap["duration_s"], d["driver_number"], lap["lap_number"])
        for d in catalog["drivers"] for lap in d["laps"]
        if lap["duration_s"] is not None and lap["has_car_telemetry"]
        and lap["lap_number"] >= 2 and not lap["is_pit_out_lap"] and lap["deleted"] is not True)
    first = eligible[0]
    second = next(e for e in eligible if e[1] != first[1])
    return (first[1], first[2]), (second[1], second[2])


def _client(rec):
    os.environ["RECORDINGS_DIR"] = str(rec.parent)
    os.environ["DATABASE_URL"] = "postgresql://nobody:nothing@127.0.0.1:9/none"
    from fastapi.testclient import TestClient

    from app.api import HubRegistry, create_app
    from app.config import get_settings
    get_settings.cache_clear()
    return TestClient(create_app(HubRegistry()))


def _get(client, url, **params):
    r = client.get(url, params=params)
    if r.status_code != 200:
        raise SystemExit(f"{url}: HTTP {r.status_code} {r.text[:300]}")
    return r


def _lap40() -> datetime:
    frames = json.loads(TIMELINE.read_text(encoding="utf-8"))["frames"]
    return datetime.fromisoformat(next(f for f in frames
                                       if f["kind"] == "LAP" and f["lap"] == 40)["at"])


def _request(pair) -> dict:
    cited = json.loads(CIRCUITS.read_text(encoding="utf-8"))["Zandvoort"]
    (da, la), (db, lb) = pair
    return {"driver_a": da, "lap_a": la, "driver_b": db, "lap_b": lb,
            "lap_length_m": cited["lap_length_m"], "lap_length_source": cited["source"]}


def build_fixture(client) -> dict:
    base = f"/api/v1/sessions/{SID}"
    catalog = _get(client, f"{base}/laps").json()
    pair = pick_pair(catalog)
    q = _request(pair)
    evidence = json.loads(_get(client, f"{base}/evidence/lap-comparison", **q).content)
    spatial = json.loads(_get(client, f"{base}/evidence/lap-comparison/spatial", **q).content)
    t = _lap40()
    t0, t1 = (t - timedelta(seconds=HALF_WINDOW_S)).isoformat(), \
        (t + timedelta(seconds=HALF_WINDOW_S)).isoformat()
    driver = pair[0][0]
    telemetry = _get(client, f"{base}/telemetry/{driver}", start=t0, end=t1,
                     frequency="RAW", fields=TELEMETRY_FIELDS).json()
    trace = json.loads(_get(client, f"{base}/spatial/{driver}", **{"from": t0, "to": t1}).content)
    sessions = _get(client, "/api/v1/sessions").json()
    return {
        "provenance": {"source": "scripts/evidence_fixture.py", "recording": NAME,
                       "session_id": SID, "pair": [list(p) for p in pair],
                       "cursor": t.isoformat(), "request": q},
        "recorded_session": next(s for s in sessions["recorded"] if s["session_id"] == SID),
        "catalog": {"session_id": catalog["session_id"],
                    "drivers": [d for d in catalog["drivers"]
                                if d["driver_number"] in (pair[0][0], pair[1][0])]},
        "evidence": evidence, "evidence_spatial": spatial,
        "telemetry": telemetry, "trace": trace,
    }


def _median_ms(fn, n: int = 15) -> tuple[float, int]:
    times, size = [], 0
    for _ in range(n):
        q0 = time.perf_counter()
        size = fn()
        times.append((time.perf_counter() - q0) * 1000)
    return statistics.median(times), size


def measure(rec, client) -> None:
    from app.storage import recording_store as rs

    st = (rec / "frames.jsonl.zst").stat()
    key = f"{rs.STORE_VERSION}|{st.st_size}|{st.st_mtime_ns}"
    q0 = time.perf_counter()
    data = rs._build(rec, SID, key)
    cold = time.perf_counter() - q0
    q0 = time.perf_counter()
    rs._read(rec, SID, key)
    warm = time.perf_counter() - q0
    sizes = {name: (rec / name).stat().st_size for name in (rs.LAPS_NAME, rs.BIN_NAME)}
    print(f"recording store: cold build {cold:.1f} s, warm load {warm:.2f} s, "
          f"{data.doc['counts']['car_rows']:,} car rows, "
          f"{data.doc['counts']['location_rows']:,} location rows, "
          f"caches {sizes[rs.LAPS_NAME] / 1e6:.2f} MB + {sizes[rs.BIN_NAME] / 1e6:.1f} MB")
    base = f"/api/v1/sessions/{SID}"
    catalog = _get(client, f"{base}/laps").json()
    q = _request(pick_pair(catalog))
    t = _lap40()
    t0, t1 = (t - timedelta(seconds=HALF_WINDOW_S)).isoformat(), \
        (t + timedelta(seconds=HALF_WINDOW_S)).isoformat()
    routes = {
        "laps catalog": lambda: len(_get(client, f"{base}/laps").content),
        "telemetry RAW 120 s": lambda: len(_get(
            client, f"{base}/telemetry/{q['driver_a']}", start=t0, end=t1, frequency="RAW",
            fields=TELEMETRY_FIELDS).content),
        "evidence_v1": lambda: len(_get(client, f"{base}/evidence/lap-comparison",
                                        **q).content),
        "evidence_spatial_v1": lambda: len(_get(
            client, f"{base}/evidence/lap-comparison/spatial", **q).content),
    }
    for name, fn in routes.items():
        fn()  # warm
        ms, size = _median_ms(fn)
        print(f"{name}: median {ms:.1f} ms of 15, {size / 1e3:.1f} kB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true", help="time the store and the routes")
    args = ap.parse_args()
    rec = find_recording()
    if rec is None:
        print("no recording")
        return 2
    client = _client(rec)
    body = to_canonical_json(build_fixture(client))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(body + b"\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(body)} bytes)")
    if args.measure:
        measure(rec, client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
