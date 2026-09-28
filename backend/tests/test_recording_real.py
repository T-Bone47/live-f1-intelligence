"""Phase 12C Task 2, REAL data: the 2026 Dutch GP recording as an evidence source.

The pair is chosen by a fixed rule (never by hand): the overall fastest
eligible lap, then the fastest eligible lap of another driver. Eligible =
timed, car telemetry inside its window, lap >= 2, not a pit-out lap, not
deleted. Every checked value is recomputed from the raw frames through an
independent parse. Skips without the recording.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import HubRegistry, create_app
from app.core.models import Lap, TelemetryCarSample
from app.evidence import parse_evidence, to_canonical_json
from app.evidence.lap_comparison import input_digest
from app.ingest.recorder import iter_recording_models
from app.storage.recording_store import RecordingStore

REPO = Path(__file__).resolve().parents[2]
NAME, SID = "openf1-11353-race", "openf1:11353"
CIRCUITS = REPO / "backend" / "app" / "spatial" / "circuits.json"


def _find_recording() -> Path | None:
    env = os.environ.get("F1INTEL_TIMELINE_RECORDING")
    if env:
        return Path(env) if (Path(env) / "meta.json").exists() else None
    for c in sorted((REPO / "recordings").glob(f"**/{NAME}")):
        if (c / "meta.json").exists() and (c / "frames.jsonl.zst").exists():
            return c
    return None


RECORDING = _find_recording()
pytestmark = pytest.mark.skipif(RECORDING is None,
                                reason=f"real recording {NAME} (with meta.json) not present")


def pick_pair(catalog: dict) -> tuple[tuple[int, int, float], tuple[int, int, float]]:
    eligible = sorted(
        (lap["duration_s"], d["driver_number"], lap["lap_number"])
        for d in catalog["drivers"] for lap in d["laps"]
        if lap["duration_s"] is not None and lap["has_car_telemetry"]
        and lap["lap_number"] >= 2 and not lap["is_pit_out_lap"] and lap["deleted"] is not True)
    first = eligible[0]
    second = next(e for e in eligible if e[1] != first[1])
    return (first[1], first[2], first[0]), (second[1], second[2], second[0])


@pytest.fixture(scope="module")
def recorded():
    store = RecordingStore(RECORDING.parent)
    catalog = store.lap_catalog(SID)
    return store, catalog, pick_pair(catalog)


@pytest.fixture(scope="module")
def raw(recorded):
    """Laps, corrections and the pair's car rows, parsed straight from the frames."""
    _store, _catalog, (a, b) = recorded
    laps: dict[tuple[int, int], dict] = {}
    corrections: dict[tuple[int, int], str] = {}
    car: dict[int, list[dict]] = {a[0]: [], b[0]: []}
    for _meta, m in iter_recording_models(RECORDING / "frames.jsonl.zst",
                                          frozenset({"Lap", "LapCorrection",
                                                     "TelemetryCarSample"})):
        if m["type"] == "Lap" and m.get("started_at") is not None:
            laps[(m["driver_number"], m["lap_number"])] = m
        elif m["type"] == "LapCorrection":
            corrections[(m["driver_number"], m["lap_number"])] = m["kind"]
        elif m["type"] == "TelemetryCarSample" and m["driver_number"] in car:
            car[m["driver_number"]].append(m)
    return laps, corrections, car


@pytest.fixture(scope="module")
def client(recorded):
    os.environ["RECORDINGS_DIR"] = str(RECORDING.parent)
    os.environ["DATABASE_URL"] = "postgresql://nobody:nothing@127.0.0.1:9/none"
    from app.config import get_settings
    get_settings.cache_clear()
    yield TestClient(create_app(HubRegistry()))
    get_settings.cache_clear()


def _lap_window_rows(raw_laps, rows, driver, lap_number):
    lap = Lap.model_validate({k: v for k, v in raw_laps[(driver, lap_number)].items()
                              if k != "type"})
    end = lap.started_at + timedelta(seconds=lap.duration_s)
    samples = sorted({(s.ts, s.model_dump_json(exclude={"provenance"})): s
                      for s in (TelemetryCarSample.model_validate(
                          {k: v for k, v in r.items() if k != "type"}) for r in rows)
                      if lap.started_at <= s.ts <= end}.values(), key=lambda s: s.ts)
    return lap, samples


def test_dutch_gp_pair_evidence_builds_and_validates(recorded, raw, client):
    _store, _catalog, (a, b) = recorded
    cited = json.loads(CIRCUITS.read_text(encoding="utf-8"))["Zandvoort"]
    r = client.get(f"/api/v1/sessions/{SID}/evidence/lap-comparison", params={
        "driver_a": a[0], "lap_a": a[1], "driver_b": b[0], "lap_b": b[1],
        "lap_length_m": cited["lap_length_m"], "lap_length_source": cited["source"]})
    assert r.status_code == 200, r.text
    assert r.headers["X-Data-Source"] == "recording"
    evidence = parse_evidence(r.content)
    assert to_canonical_json(evidence) == r.content  # validated, round-trips byte for byte
    ca, cb = evidence.comparison.driver_a, evidence.comparison.driver_b
    assert (ca.driver_number, ca.lap_number) == a[:2]
    assert (cb.driver_number, cb.lap_number) == b[:2]
    assert evidence.source.circuit == "Zandvoort" and evidence.source.season == 2026

    laps, _corr, car = raw
    lap_a, samples_a = _lap_window_rows(laps, car[a[0]], a[0], a[1])
    lap_b, samples_b = _lap_window_rows(laps, car[b[0]], b[0], b[1])
    assert evidence.provenance.input_digest == input_digest(lap_a, samples_a, lap_b, samples_b)


def test_catalog_matches_the_raw_rows(recorded, raw):
    store, catalog, _pair = recorded
    laps, corrections, _car = raw
    got = {(d["driver_number"], lap["lap_number"]): lap
           for d in catalog["drivers"] for lap in d["laps"]}
    assert set(got) == set(laps)
    for key, lap in got.items():
        assert lap["duration_s"] == laps[key].get("duration_s")
        kind = corrections.get(key)
        assert lap["deleted"] is {"LAP_DELETED": True, "LAP_REINSTATED": False}.get(kind)
    # A correction can name a lap the recording has no row for (#22 lap 43 on
    # this race): it is counted, never turned into a fabricated lap.
    with_row = {k: kind for k, kind in corrections.items() if k in laps}
    assert sum(lap["deleted"] is True for lap in got.values()) == \
        sum(kind == "LAP_DELETED" for kind in with_row.values())
    counts = store.counts(SID)
    assert counts["corrections"] >= len(corrections)
    assert counts["car_duplicate_conflicting"] == 0  # so the database's first-row rule agrees


def test_dutch_gp_pair_is_placed_on_the_validated_track(recorded, client):
    from datetime import datetime

    from app.api import _spatial_store
    from app.spatial.evidence_spatial import validate_evidence_spatial
    from app.spatial.state import state_at

    _store, _catalog, (a, b) = recorded
    cited = json.loads(CIRCUITS.read_text(encoding="utf-8"))["Zandvoort"]
    q = {"driver_a": a[0], "lap_a": a[1], "driver_b": b[0], "lap_b": b[1],
         "lap_length_m": cited["lap_length_m"], "lap_length_source": cited["source"]}
    ev = client.get(f"/api/v1/sessions/{SID}/evidence/lap-comparison", params=q)
    r = client.get(f"/api/v1/sessions/{SID}/evidence/lap-comparison/spatial", params=q)
    assert r.status_code == 200, r.text
    assert r.headers["X-Evidence-Id"] == ev.headers["X-Evidence-Id"]
    doc, evidence = json.loads(r.content), json.loads(ev.content)
    validate_evidence_spatial(doc, evidence)
    index = _spatial_store(RECORDING.parent).get_index(SID)
    placed = 0
    for seg in doc["segments"]:
        for side, driver in (("a", a[0]), ("b", b[0])):
            ext = seg[side]
            if ext["status"] != "PLACED":
                continue
            placed += 1
            for ts, frac, xy in ((ext["from_ts"], ext["from_fraction"], ext["from_xy"]),
                                 (ext["to_ts"], ext["to_fraction"], ext["to_xy"])):
                entry = next(e for e in state_at(index, datetime.fromisoformat(ts).timestamp())
                             if e["driver_number"] == driver)
                assert entry["reference_fraction"] == frac and [entry["x"], entry["y"]] == xy
    # every covered segment of two timed racing laps lies on the reference
    covered = sum(2 for s in evidence["attribution"]["segments"]
                  if s["attribution_status"] != "NO_DATA")
    assert placed == covered
    codes = {lim["code"] for lim in doc["limitations"]}
    assert "CORNER_PRECISION_NOT_MET" in codes  # the Dutch GP corner gate failed (12A)
