"""Phase 10.5: golden evidence_v1 fixture + exported JSON Schema.

    cd backend
    python ../scripts/evidence_report.py

Writes (deterministic - a re-run is byte-identical):
- docs/evidence/evidence_v1_singapore.json  canonical evidence_v1 bytes for the
  real pair (session 9161, #55 lap 19 vs #63 lap 16), built through the
  production path raw OpenF1 rows -> identity guard -> 10.1B -> 10.4 -> 10.5;
- docs/evidence/evidence_v1.schema.json     JSON Schema of the contract.
Source metadata comes only from the fixture's meta.json: it records no
meeting name, so `event` is null rather than invented.
"""

from __future__ import annotations

import json
from pathlib import Path

from _common import setup_logging  # noqa: F401  (puts backend/ on sys.path)

from app.evidence import SourceInfo, build_lap_comparison_evidence, to_canonical_json
from app.evidence.schema import json_schema
from app.providers.openf1.mapping import to_car_sample, to_lap
from app.providers.openf1.real_data import validate_rows_identity

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "scripts" / "fixtures" / "real-openf1-pair"
GOLDEN = ROOT / "docs" / "evidence" / "evidence_v1_singapore.json"
SCHEMA = ROOT / "docs" / "evidence" / "evidence_v1.schema.json"


def build_real_evidence(fixture: Path = FIXTURE):
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
    source = SourceInfo(session_id=sid, provider=meta["provider"],
                        session_type=meta.get("session_type"), season=meta.get("year"),
                        event=None, circuit=meta.get("circuit_short_name"))
    a, b = meta["driver_a"], meta["driver_b"]
    return build_lap_comparison_evidence(
        laps[a], samples[a], laps[b], samples[b], lap_length_m=meta["lap_length_m"],
        lap_length_source=meta["lap_length_source"], source=source)


def main() -> None:
    evidence = build_real_evidence()
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_bytes(to_canonical_json(evidence) + b"\n")
    SCHEMA.write_text(json.dumps(json_schema(), indent=1, sort_keys=True) + "\n",
                      encoding="utf-8")
    segs = evidence.attribution.segments
    print(f"wrote {GOLDEN.name} ({GOLDEN.stat().st_size} bytes, {evidence.evidence_id}, "
          f"{len(segs)} segments, {sum(s.significant for s in segs)} significant) "
          f"and {SCHEMA.name}")


if __name__ == "__main__":
    main()
