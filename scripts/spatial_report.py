"""Phase 12A: build track_reference_v1 from a recording, report its validation
and the open items the spec leaves to the data (and write the golden).

    cd backend
    python ../scripts/spatial_report.py                 # report only
    python ../scripts/spatial_report.py --write-golden  # + docs/spatial golden

Default recording: recordings/**/openf1-11353-race (2026 Dutch GP race).
Deterministic: a re-run on the same recording gives the same bytes.
"""

from __future__ import annotations

import argparse
import bisect
import math
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

from app.analysis.common.models import Confidence
from app.analysis.timeline import to_canonical_json
from app.ingest.recorder import iter_recording_models
from app.spatial.builder import build_spatial
from app.spatial.samples import SampleFlag
from app.spatial.source import load_inputs
from app.spatial.state import CONF_CODES, FLAG_CODES
from app.storage.timeline_store import index_recordings

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "docs" / "spatial" / "track_reference_v1_dutch_gp_2026.json"
NAME = "openf1-11353-race"
SID = "openf1:11353"


def find_recording() -> Path | None:
    for c in sorted((ROOT / "recordings").glob(f"**/{NAME}")):
        if (c / "meta.json").exists() and (c / "frames.jsonl.zst").exists():
            return c
    return None


def utc(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%H:%M:%S.%f")[:-3] + "Z"


def report_lines(doc: dict) -> None:
    print("\nTIMING LINES (dispersion in metres, nearest-rank)")
    for line in doc["timing_lines"]:
        d = line["dispersion_m"] or {}
        ex = {k: v for k, v in line["exclusions"].items() if v}
        print(f"  {line['line']:6s} n={line['n']:4d} at {line['distance_m']!s:>22} m  "
              f"median {d.get('median', math.nan):6.2f}  p90 {d.get('p90', math.nan):6.2f}  "
              f"p95 {d.get('p95', math.nan):6.2f}  p99 {d.get('p99', math.nan):7.2f}  "
              f"max {d.get('max', math.nan):8.2f}  excluded {ex}")


def report_worst(doc: dict, inputs) -> None:
    print("\nWORST CROSSINGS (data around each probe)")
    for line in doc["timing_lines"]:
        for w in line["worst"]:
            d, lap = w["driver_number"], w["lap_number"]
            row = next(r for r in inputs.laps[d] if r.lap == lap)
            probe = row.start + (0 if line["line"] == "FINISH" else
                                 (row.s1 or 0) + (0 if line["line"] == "S1" else (row.s2 or 0)))
            ts = [s[0] for s in inputs.samples.get(d, ())]
            i = bisect.bisect_left(ts, probe)
            gap = ts[i] - ts[i - 1] if 0 < i < len(ts) else math.nan
            pits = [(utc(p.ts), p.lap, p.lane_s) for p in inputs.pits.get(d, ())
                    if abs(p.ts - probe) < 600]
            print(f"  {line['line']:6s} #{d:<2} L{lap:<2} {w['value']:8.2f} {w['unit']}  "
                  f"probe {utc(probe)}  lap {row.duration}s  bracket gap {gap:.3f}s  "
                  f"pits within 10 min {pits}")


def report_no_fix(rec: Path, inputs) -> None:
    starts = [r.start for rows in inputs.laps.values() for r in rows]
    ends = [r.start + r.duration for rows in inputs.laps.values() for r in rows if r.duration]
    first, last = min(starts), max(ends)
    where: Counter = Counter()
    racing: Counter = Counter()
    for _meta, m in iter_recording_models(rec / "frames.jsonl.zst",
                                          frozenset({"TelemetryLocationSample"})):
        if m.get("x") == 0 and m.get("y") == 0 and m.get("z") == 0:
            t = datetime.fromisoformat(m["ts"]).timestamp()
            zone = "before first lap start" if t < first else "after last lap end" \
                if t > last else "between"
            where[zone] += 1
            if zone == "between":
                racing[int(m["driver_number"])] += 1
    print(f"\nNO-FIX (0,0,0) SAMPLES: {dict(where)}  first lap start {utc(first)}  "
          f"last lap end {utc(last)}")
    for d, n in racing.most_common():
        last_lap = max((r.lap for r in inputs.laps.get(d, ())), default=None)
        print(f"  between first lap start and last lap end: #{d} x{n} (last lap row L{last_lap})")


def report_withheld(index) -> None:
    if index is None:
        return
    on, none = FLAG_CODES[SampleFlag.ON_REFERENCE], CONF_CODES[Confidence.NONE]
    per_lap: Counter = Counter()
    total = 0
    for d, trk in index.tracks.items():
        for i in range(len(trk.t)):
            if trk.flag[i] == on and trk.confidence[i] == none:
                per_lap[(d, trk.lap[i])] += 1
                total += 1
    flags = Counter(f for trk in index.tracks.values() for f in trk.flag)
    names = {v: k.value for k, v in FLAG_CODES.items()}
    print(f"\nSAMPLE FLAGS: { {names[k]: v for k, v in sorted(flags.items())} }")
    lap3 = sum(n for (_d, lap), n in per_lap.items() if lap == 3)
    print(f"WITHHELD (ON_REFERENCE, confidence NONE): {total}; on lap 3: {lap3}; laps with most:")
    for (d, lap), n in per_lap.most_common(8):
        print(f"  #{d} L{lap}: {n}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recording", type=Path)
    ap.add_argument("--write-golden", action="store_true")
    args = ap.parse_args()
    rec = args.recording or find_recording()
    if rec is None:
        print(f"no complete recording named {NAME} under recordings/", file=sys.stderr)
        return 2
    sid = next((s for s, p in index_recordings(rec.parent).items() if p == rec), SID)
    t0 = time.perf_counter()
    inputs = load_inputs(rec, sid)
    t1 = time.perf_counter()
    doc, index = build_spatial(inputs)
    t2 = time.perf_counter()
    body = to_canonical_json(doc)
    print(f"{sid}: load {t1 - t0:.1f} s, build {t2 - t1:.1f} s, {len(body)} bytes, "
          f"status {doc['status']}, track_id {doc['track_id']}")
    for name, g in doc["validation"]["gates"].items():
        print(f"  gate {name}: {'PASS' if g['passed'] else 'FAIL'} (<= {g['threshold_m']} m) "
              f"p95 {g['observed_p95_m']} reasons {g['reasons']}")
    ref, v = doc["reference"], doc["validation"]
    print(f"  reference #{ref['driver_number']} L{ref['lap_number']} {ref['duration_s']} s, "
          f"{ref['point_count']} points, loop {ref['loop_length_feed_units']:.1f} units, "
          f"{doc['coordinate_system']['measured_units_per_metre']} units/m")
    print(f"  reference independence {v['reference_independence_m']} m; "
          f"candidates {doc['provenance']['reference_candidates']}")
    print(f"  on-reference tolerance {v['on_reference_tol']}")
    print(f"  pit windows {v['pit_windows']}")
    print(f"  counts {doc['provenance']['counts']}")
    print(f"  capabilities { {k: c['evidence'] for k, c in doc['capabilities'].items()} }")
    report_lines(doc)
    report_worst(doc, inputs)
    report_withheld(index)
    report_no_fix(rec, inputs)
    if args.write_golden:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(body)
        print(f"\nwrote {GOLDEN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
