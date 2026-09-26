"""Write meta.json for a recording whose recorder died or was stopped.

    cd backend
    python ../scripts/finalize_recording.py <recording dir> --note "why it stopped"

Everything is derived from the recorded frames and labelled `interrupted`,
with per-model-type counts and last source timestamps (coverage). It never
overwrites a meta.json the recorder wrote itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

from app.ingest.recorder import finalize_interrupted


def main() -> int:
    ap = argparse.ArgumentParser(description="Finalize an interrupted recording")
    ap.add_argument("recording", type=Path)
    ap.add_argument("--note", required=True, help="why the recorder stopped")
    args = ap.parse_args()
    meta = finalize_interrupted(args.recording, note=args.note)
    print(f"frames: {meta['frames']}  unreadable lines: {meta['unreadable_lines']}")
    print(json.dumps(meta["coverage"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
