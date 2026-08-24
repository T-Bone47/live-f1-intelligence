"""Direct on_lap trace (dev tool)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from datetime import datetime, timezone

ts = datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc)
from app.core.models import Lap  # noqa: E402

lap = Lap(session_id="s", driver_number=1, lap_number=1, started_at=ts,
          duration_s=85.0, sector1_s=None, sector2_s=None, sector3_s=None,
          is_pit_out_lap=False,
          speed_traps={"i1_kph": None, "i2_kph": None, "st_kph": None},
          provenance={"provider": "openf1", "source_timestamp": ts.isoformat(),
                      "ingestion_timestamp": ts.isoformat(),
                      "provenance_class": "A"})

from app.analysis import AnalysisEngine  # noqa: E402
from app.core.events import Envelope  # noqa: E402

env = Envelope(event_type="x", session_id="s", source="t",
               ingestion_timestamp=datetime.now(timezone.utc),
               provenance_class="A", payload={"model": {"type": "Lap"}})
eng = AnalysisEngine("s")
deleted = eng._corr_open.get((lap.driver_number, lap.lap_number), False)

from app.analysis.laps import ClassifiedLap  # noqa: E402

cl = ClassifiedLap(session_id=lap.session_id, driver_number=lap.driver_number,
                   lap_number=lap.lap_number, started_at=lap.started_at,
                   duration_s=lap.duration_s,
                   sector_times_s=(lap.sector1_s, lap.sector2_s, lap.sector3_s),
                   is_pit_out=lap.is_pit_out_lap or False, deleted=deleted)
classified = eng.classifier.classify(cl)
print("class:", classified.lap_class, "flags:", classified.flags)
result = eng.timing.fold_lap(driver_number=1, lap_number=1,
                             duration_s=85.0, deleted=False)
print("fold result:", result)
pb = bool(result and result.get("personal_best"))
sb = bool(result and result.get("session_best"))
out = eng.sig.lap_completed(driver_number=1, lap_number=1, duration_s=85.0,
                            personal_best=pb, session_best_change=sb,
                            is_first_sb=False, ts=ts)
print("events:", [o.event_type for o in out])
