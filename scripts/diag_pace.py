"""Probe: why are representative laps empty? Run analysis on a slice of the
recording and dump classified-lap stats."""

import asyncio
import sys
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analysis import AnalysisEngine  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.ingest.pipeline import IngestPipeline  # noqa: E402
from app.providers.replay import ReplayProvider  # noqa: E402


async def main() -> None:
    get_settings()
    rec = Path("recordings/openf1-11353-race")
    provider = ReplayProvider(rec)
    provider.set_speed(0)
    session = await provider.resolve_session(str(rec))
    pipeline = IngestPipeline(session_id=session.session_id)
    engine = AnalysisEngine(session_id="openf1:11353")

    classes = Counter()
    flag_combos = Counter()

    async def on_env(env) -> None:  # noqa: ANN001
        info = env.payload.get("model", {})
        if info.get("type") == "Lap":
            # replicate engine path to observe classification
            from app.analysis.laps import ClassifiedLap
            from app.core.models import Lap as LapModel

            m = LapModel.model_validate({k: v for k, v in info.items() if k != "type"})
            cl = ClassifiedLap(
                session_id=m.session_id, driver_number=m.driver_number,
                lap_number=m.lap_number, started_at=m.started_at,
                duration_s=m.duration_s,
                sector_times_s=(m.sector1_s, m.sector2_s, m.sector3_s),
                is_pit_out=m.is_pit_out_lap or False,
                deleted=False,
                stint_number=engine.stints.current_stint.get(m.driver_number),
            )
            classified = engine.classifier.classify(cl)
            classes[classified.lap_class.value] += 1
            flag_combos[tuple(sorted(classified.flags))[:4]] += 1
        engine.process_envelope(env)

    pipeline.bus.subscribe("probe", on_env)
    count = 0
    async for item in provider.run(session):
        count += await pipeline.process(item)

    print("laps seen:", sum(classes.values()))
    print("classes:", dict(classes))
    print("top flag combos:", flag_combos.most_common(6))
    p1 = engine.pace._driver(1)
    print("driver1 representative:", len(p1.representative_laps),
          "excluded:", len(p1.excluded))
    print("driver1 rolling5:", engine.pace.rolling_pace(1, 5))


if __name__ == "__main__":
    asyncio.run(main())
