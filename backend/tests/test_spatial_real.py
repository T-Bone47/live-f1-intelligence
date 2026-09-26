"""Phase 12A real-data validation on the 2026 Dutch GP race (OpenF1 11353).

Skips without the recording. Every value checked here is either recomputed
independently from the raw rows (no Centerline, no window search, own
interpolation and percentiles) or pinned as a measured fact documented in
docs/PHASE_12_SPATIAL_VALIDATION.md.
"""

from __future__ import annotations

import bisect
import io
import json
import math
import os
import random
import statistics
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import pytest

from app.analysis.common.models import Confidence
from app.analysis.timeline import to_canonical_json
from app.analysis.track_geometry import Centerline
from app.spatial.builder import build_spatial
from app.spatial.samples import SampleFlag
from app.spatial.source import load_inputs
from app.spatial.state import CONF_CODES, FLAG_CODES, state_at

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "docs" / "spatial" / "track_reference_v1_dutch_gp_2026.json"
TIMELINE = REPO / "docs" / "timeline" / "session_timeline_v1_dutch_gp_2026.json"
NAME, SID, LAP_M = "openf1-11353-race", "openf1:11353", 4259.0


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


@pytest.fixture(scope="module")
def built():
    inputs = load_inputs(RECORDING, SID)
    doc, index = build_spatial(inputs)
    return inputs, doc, index


def _line(doc: dict, name: str) -> dict:
    return next(line for line in doc["timing_lines"] if line["line"] == name)


def test_real_inputs_account_for_every_location_row(built):
    from zstandard import ZstdDecompressor

    inputs, _doc, _index = built
    raw = 0
    with open(RECORDING / "frames.jsonl.zst", "rb") as fh:
        for line in io.BufferedReader(ZstdDecompressor().stream_reader(fh, read_across_frames=True)):
            raw += b'"type":"TelemetryLocationSample"' in line
    c = inputs.counts
    kept = sum(len(s) for s in inputs.samples.values())
    assert raw == 890_494
    assert kept + c["no_fix"] + c["null_xy"] + c["duplicate_identical"] + \
        c["duplicate_conflicting"] == raw
    assert c["no_fix"] == 83_783 and c["null_xy"] == 0
    assert len(inputs.drivers) == 22
    assert c["car_samples"] == c["car_drs_null"] == 900_900


def test_real_gate_map_sector_passes_and_corner_fails(built):
    _inputs, doc, index = built
    assert doc["status"] == "VALIDATED_MAP_SECTOR" and index is not None
    gates = doc["validation"]["gates"]
    assert gates["MAP_SECTOR"]["passed"] and not gates["CORNER"]["passed"]
    for name in ("FINISH", "S1", "S2"):
        assert 5.0 < _line(doc, name)["dispersion_m"]["p95"] <= 20.0


def _brute_fraction(polyline: list[list[float]], x: float, y: float) -> float:
    best, cum = None, 0.0
    for (x0, y0), (x1, y1) in pairwise(polyline):
        dx, dy = x1 - x0, y1 - y0
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / seg2))
        d = math.hypot(x - (x0 + t * dx), y - (y0 + t * dy))
        if best is None or d < best[0]:
            best = (d, cum + t * math.sqrt(seg2))
        cum += math.sqrt(seg2)
    return best[1] / cum


def _interp(samples, times, t):
    if not times or t < times[0] or t > times[-1]:
        return None
    hi = bisect.bisect_left(times, t)
    if times[hi] == t:
        return samples[hi][1], samples[hi][2]
    (t0, x0, y0), (t1, x1, y1) = samples[hi - 1], samples[hi]
    if t1 - t0 > 2.0:
        return None
    a = (t - t0) / (t1 - t0)
    return x0 + a * (x1 - x0), y0 + a * (y1 - y0)


def _rank(values, q):
    v = sorted(values)
    return v[math.ceil(q * len(v)) - 1]


def test_real_line_dispersion_matches_independent_brute_force(built):
    inputs, doc, _index = built
    poly = doc["reference"]["polyline"]
    pitted = {(d, p.lap) for d, stops in inputs.pits.items() for p in stops if p.lap is not None}
    crossings: dict[str, list[float]] = {"FINISH": [], "S1": [], "S2": []}
    for d, laps in inputs.laps.items():
        samples = inputs.samples.get(d, ())
        times = [s[0] for s in samples]
        for r in laps:
            if r.lap < 2 or r.duration is None or r.pit_out or (d, r.lap) in pitted \
                    or (d, r.lap - 1) in pitted:
                continue
            probes = {"FINISH": r.start}
            if r.s1 is not None:
                probes["S1"] = r.start + r.s1
                if r.s2 is not None:
                    probes["S2"] = r.start + r.s1 + r.s2
            for name, t in probes.items():
                p = _interp(samples, times, t)
                if p is not None:
                    crossings[name].append(_brute_fraction(poly, *p))
    for name, fr in crossings.items():
        if name == "FINISH":
            fr = [f - 1.0 if f > 0.5 else f for f in fr]
        med = statistics.median(fr)
        dev = [abs(f - med) * LAP_M for f in fr]
        got = _line(doc, name)
        assert got["n"] == len(fr)
        for key, q in (("median", 0.5), ("p90", 0.9), ("p95", 0.95), ("p99", 0.99)):
            assert abs(got["dispersion_m"][key] - _rank(dev, q)) < 1e-6, (name, key)
        assert abs(got["dispersion_m"]["max"] - max(dev)) < 1e-6
        crossings[name] = fr
    fin = statistics.median(crossings["FINISH"])
    for name in ("S1", "S2"):
        expected = ((statistics.median(crossings[name]) - fin) % 1.0) * LAP_M
        assert abs(_line(doc, name)["distance_m"] - expected) < 1e-6


def test_real_reference_independence_within_20_m(built):
    _inputs, doc, _index = built
    assert doc["validation"]["reference_independence_m"] <= 20.0
    assert len(doc["provenance"]["reference_candidates"]) == 3


def test_real_capabilities_are_evidenced(built):
    _inputs, doc, _index = built
    caps, tol = doc["capabilities"], doc["validation"]["on_reference_tol"]
    assert all(c["available"] is False for c in caps.values())
    assert caps["racing_line"]["evidence"]["p999"] == tol["feed_units"]
    assert caps["drs_zones"]["evidence"] == {"car_samples": 900_900, "drs_null": 900_900}
    codes = {lim["code"] for lim in doc["limitations"]}
    assert {"DRS_DATA_ABSENT", "CORNER_PRECISION_NOT_MET", "CORNERS_UNAVAILABLE",
            "FEED_LINE_NOT_RACING_LINE"} <= codes


def test_real_pit_windows_have_exit_semantics(built):
    _inputs, doc, _index = built
    pit, tol = doc["validation"]["pit_windows"], doc["validation"]["on_reference_tol"]
    assert pit["mode"] == "EXIT" and pit["share_exit"] >= 0.9 and pit["share_entry"] < 0.1
    # pit entry/exit roads meet the track: some window samples sit on the line
    assert tol["provisional"] is True and tol["pit_inside_share"] >= 0.001


def test_real_lap_frames_put_the_lap_completer_on_the_finish_line(built):
    """Phase 11 x 12A: a LAP k frame is the moment a car completes lap k by
    official timing (the frame's P1 row can lag it - lap 44). At that moment
    12A must put that car on the finish line - or say why it cannot: pit
    lane, a stale location feed, or a withheld sample."""
    inputs, doc, index = built
    finish = _line(doc, "FINISH")["dispersion_m"]
    done = {(d, r.lap): r.start + r.duration
            for d, laps in inputs.laps.items() for r in laps if r.duration is not None}
    frames = [f for f in json.loads(TIMELINE.read_text(encoding="utf-8"))["frames"]
              if f["kind"] == "LAP"]
    on_line, explained = [], []
    for f in frames:
        t, k = datetime.fromisoformat(f["at"]).timestamp(), f["lap"]
        car = min((d for (d, lap) in done if lap == k), key=lambda d: done[(d, k)])
        assert abs(done[(car, k)] - t) < 1e-3
        e = next(e for e in state_at(index, t) if e["driver_number"] == car)
        frac = e["reference_fraction"]
        if e["status"] == "STALE" or frac is None:
            assert e["status"] == "STALE" or e["flag"] == "PIT_LANE" or                 e["confidence"] in ("LOW", "NONE"), (k, e)
            explained.append(k)
        else:
            on_line.append(min(frac, 1.0 - frac) * LAP_M)
    assert len(on_line) + len(explained) == len(frames) == 72
    assert sum(d <= finish["p95"] for d in on_line) >= 0.95 * len(on_line)
    assert max(on_line) <= finish["max"]


def test_real_withheld_samples_concentrate_on_the_restart_lap(built):
    _inputs, _doc, index = built
    on, none = FLAG_CODES[SampleFlag.ON_REFERENCE], CONF_CODES[Confidence.NONE]
    laps = [trk.lap[i] for trk in index.tracks.values() for i in range(len(trk.t))
            if trk.flag[i] == on and trk.confidence[i] == none]
    assert len(laps) == 12_494 and sum(lap == 3 for lap in laps) / len(laps) >= 0.8


def test_real_narrow_window_projection_equals_global_search(built):
    inputs, doc, _index = built
    pts = [tuple(p) for p in doc["reference"]["polyline"]]
    narrow, full = Centerline(pts, 8), Centerline(pts, 10**6)
    rng = random.Random(21)
    for _ in range(20):
        d = rng.choice(sorted(inputs.samples))
        samples = inputs.samples[d]
        start = rng.randrange(max(1, len(samples) - 250))
        hint = None
        for _t, x, y in samples[start:start + 250]:
            p, g = narrow.project(x, y, hint), full.project(x, y, None)
            assert (p.s, p.offset) == (g.s, g.offset)
            hint = p.segment


def test_real_output_matches_the_committed_golden(built):
    _inputs, doc, _index = built
    assert to_canonical_json(doc) == GOLDEN.read_bytes()
