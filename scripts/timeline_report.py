"""Phase 11: build a session_timeline_v1 from a recording (and the golden).

    cd backend
    python ../scripts/timeline_report.py                       # the golden
    python ../scripts/timeline_report.py --recording <dir> --out <file.json>

Default: finds recordings/**/openf1-11353-race (the real 2026 Dutch GP race,
recorded with scripts/record_session.py; it must be complete, i.e. have
meta.json) and writes docs/timeline/session_timeline_v1_dutch_gp_2026.json.
Deterministic: a re-run on the same recording is byte-identical. The build
folds the recorded canonical envelopes (telemetry skipped - the engine does
not use it) through AnalysisEngine in race order; see app/analysis/timeline.py.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

from app.analysis.timeline import (
    build_timeline_from_recording,
    to_canonical_json,
    validate_timeline,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "docs" / "timeline" / "session_timeline_v1_dutch_gp_2026.json"
NAME = "openf1-11353-race"


def find_recording() -> Path | None:
    for c in sorted((ROOT / "recordings").glob(f"**/{NAME}")):
        if (c / "meta.json").exists() and (c / "frames.jsonl.zst").exists():
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a session_timeline_v1 from a recording")
    ap.add_argument("--recording", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=GOLDEN)
    args = ap.parse_args()
    rec = args.recording or find_recording()
    if rec is None or not (rec / "meta.json").exists():
        print(f"no complete recording found (need {NAME} with meta.json)")
        return 2
    t0 = time.perf_counter()
    tl = build_timeline_from_recording(rec)
    validate_timeline(tl)
    body = to_canonical_json(tl) + b"\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(body)
    print(f"recording : {rec}")
    print(f"frames    : {len(tl['frames'])} (laps completed max {tl['laps_completed_max']})")
    print(f"source    : {tl['source']}")
    print(f"written   : {args.out} ({len(body):,} bytes) in {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
