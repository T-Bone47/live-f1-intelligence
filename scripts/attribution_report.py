"""Phase 10.4 machine-readable attribution report for a real two-driver fixture.

    cd backend
    python ../scripts/attribution_report.py [fixture_dir] [--out path] [--print]

Runs raw OpenF1 rows -> identity guard -> 10.1B -> 10.1C -> 10.2 -> 10.4 and
writes JSON with: the full attribution (every segment, not a selection),
the Phase 10.5 context pack, and the fixture's provenance. Deterministic:
no wall-clock time is written, so a re-run is byte-identical and
backend/tests/test_attribution_real_pair.py can lock it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

from app.analysis.attribution import attribute_comparison, attribution_facts, report_to_dict
from app.analysis.delta_analysis import analyze_delta
from app.analysis.lap_comparison import compare_driver_laps
from app.providers.openf1.mapping import to_car_sample, to_lap
from app.providers.openf1.real_data import validate_rows_identity

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
DEFAULT_OUT = ROOT / "docs" / "evidence" / "phase_10_4_singapore_attribution.json"


def build(fixture: Path) -> dict:
    meta = json.loads((fixture / "meta.json").read_text())
    sid = f"openf1:{meta['session_key']}"
    laps, samples = {}, {}
    for d in (meta["driver_a"], meta["driver_b"]):
        lap_row = json.loads((fixture / f"driver_{d}_lap.json").read_text())
        car = json.loads((fixture / f"driver_{d}_car_data.json").read_text())
        validate_rows_identity(car, driver_number=d, session_key=meta["session_key"])
        validate_rows_identity([lap_row], driver_number=d, session_key=meta["session_key"])
        laps[d], _ = to_lap(lap_row, sid)
        samples[d] = sorted((to_car_sample(r, sid) for r in car), key=lambda s: s.ts)
    a, b = meta["driver_a"], meta["driver_b"]
    cmp = compare_driver_laps(laps[a], samples[a], None, laps[b], samples[b], None,
                              lap_length_m=meta["lap_length_m"])
    report = attribute_comparison(analyze_delta(cmp), laps[a], laps[b])
    return {
        "kind": "Phase 10.4 deterministic attribution - REAL OpenF1 data",
        "fixture": {
            "path": "scripts/fixtures/real-openf1-pair",
            "session_key": meta["session_key"], "driver_a": a, "lap_a": meta["lap_a"],
            "driver_b": b, "lap_b": meta["lap_b"],
            "lap_length_m": meta["lap_length_m"],
            "lap_length_source": meta["lap_length_source"],
            "car_data_rows": {str(d): len(samples[d]) for d in (a, b)},
        },
        "attribution": json.loads(json.dumps(report_to_dict(report))),
        "context_pack": json.loads(json.dumps(attribution_facts(report))),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--print", action="store_true", help="print a segment table")
    args = ap.parse_args()
    doc = build(args.fixture)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    att = doc["attribution"]
    print(f"wrote {args.out.name}: {len(att['segments'])} segments, misalignment bound "
          f"{att['uncertainty']['misalignment_bound_m']:.3f} m ({att['uncertainty']['source']})")
    if args.print:
        for s in att["segments"]:
            if s["accumulated_change_s"] is None:
                print(f"  {s['region_id']} NO_DATA x {s['x_start']:.3f}-{s['x_end']:.3f}")
                continue
            print(f"  {s['region_id']} {s['distance_start_m']:6.0f}-{s['distance_end_m']:6.0f} m "
                  f"gap {s['inherited_gap_s']:+.3f} change {s['accumulated_change_s']:+.3f} "
                  f"+/-{s['uncertainty_s']:.3f} {s['kind']:<10} {s['status']:<22} "
                  f"order {[o['signal'] for o in s['onset_order']]}")


if __name__ == "__main__":
    main()
