"""Build a small deterministic mini-recording fixture for realtime tests."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.analysis.common.models import Confidence  # noqa: E402
from app.core.enums import ProvenanceClass  # noqa: E402
from app.core.events import Envelope  # noqa: E402
from app.ingest.recorder import Recorder  # noqa: E402

OUT = Path(__file__).parent / "fixtures" / "mini-recording"


def env(seq_ts: datetime, mtype: str, payload: dict) -> Envelope:
    return Envelope(
        event_type="x", session_id="openf1:mini", source="openf1",
        source_timestamp=seq_ts,
        ingestion_timestamp=seq_ts + timedelta(seconds=0.3),
        provenance_class=ProvenanceClass.B,
        dedupe_key=f"{mtype}:{payload.get('lap_number', seq_ts.isoformat())}",
        payload={"model": {"type": mtype, **payload}},
    )


def main() -> None:
    rec = Recorder(OUT.parent, OUT.name)
    base = datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc)

    def prov(ts: datetime) -> dict:
        return {"provider": "openf1", "source_timestamp": ts.isoformat(),
                "ingestion_timestamp": (ts + timedelta(milliseconds=300)).isoformat(),
                "provenance_class": "B"}

    session_payload = {
        "model": {
            "type": "SessionInfo",
            "session_id": "openf1:mini", "provider": "openf1",
            "provider_session_key": "mini",
            "year": 2026, "session_type": "RACE",
            "session_name": "Mini Race", "circuit_short_name": "TestRing",
            "date_start": base.isoformat(),
            "status": "FINISHED", "is_cancelled": False,
            "provenance": prov(base),
        }
    }
    rec.write(env(base, "SessionInfo", {"model": session_payload["model"]}))

    t = base
    for lap in range(1, 9):
        t = t + timedelta(seconds=90)
        dur = 80.0 + (8 - lap) * 0.05   # improving pace
        for driver in (1, 2):
            rec.write(env(t, "Lap", {
                "session_id": "openf1:mini", "driver_number": driver,
                "lap_number": lap, "started_at": t.isoformat(),
                "duration_s": dur + driver * 0.5,
                "sector1_s": 26.0, "sector2_s": 27.0, "sector3_s": None
                if lap == 1 else 25.0,
                "is_pit_out_lap": lap == 1,
                "speed_traps": {"i1_kph": None, "i2_kph": None, "st_kph": 250},
                "deleted": False,
                "provenance": prov(t),
            }))
        # one interval sample per lap for driver 2 vs driver 1
        rec.write(env(t + timedelta(seconds=45), "TimingInterval", {
            "session_id": "openf1:mini", "driver_number": 2,
            "ts": (t + timedelta(seconds=45)).isoformat(),
            "gap_to_leader_s": 1.0 + lap * 0.1, "interval_s": 0.9 + lap * 0.05,
            "gap_raw": None,
            "provenance": prov(t),
        }))

    rec.write_meta({"session": {"session_key": "mini", "session_name": "Mini Race",
                                "year": 2026, "session_type": "RACE"}},
                   provider_name="replay")
    rec.finalize()
    print("fixture at", OUT)


if __name__ == "__main__":
    sys.exit(main())
