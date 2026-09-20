"""Build scripts/fixtures/real-openf1-9159/ from real, live-fetched OpenF1 data.

Unlike _make_mini_recording.py (synthetic, hand-crafted lap times), this
fixture is genuine F1 telemetry: 2023-09-15 (Singapore GP weekend),
session_key 9159, driver 55 (Sainz), fetched live from
https://api.openf1.org/v1/car_data - historical OpenF1 data needs no auth.
Built for the Phase 10.1A end-to-end acceptance test (Section 21's "the
end-to-end persistence gate must use real recorded F1 telemetry, not
synthetic fixtures").

raw_car_data_source.json is the exact raw API response (list of dicts with
date/driver_number/rpm/speed/n_gear/throttle/brake/drs - OpenF1's native
field names), checked in so this fixture is rebuildable without a live
fetch. Deliberately small (39 samples: 2 real 315 km/h samples plus a real
~10-second RPM warm-up sequence) - large enough to be genuinely real and
multi-sample, small enough to check into git. It's smaller than even the
lowest downsampling tier's target (120 points), so it can exercise the
persistence/query/provenance path end-to-end but not LTTB's actual point
reduction - see tests/test_downsample.py for that, which uses synthetic
data for exactly the properties that don't need real telemetry to prove.

Run from backend/: python ../scripts/build_real_openf1_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.enums import ProviderName, ProvenanceClass
from app.core.events import make_envelope
from app.core.models import Provenance, SessionInfo
from app.ingest.recorder import Recorder
from app.providers.openf1.mapping import to_car_sample

FIXTURE_DIR = Path(__file__).parent / "fixtures"
RAW_SOURCE = FIXTURE_DIR / "real-openf1-9159" / "raw_car_data_source.json"
SESSION_ID = "openf1:9159"


def build() -> None:
    with open(RAW_SOURCE) as f:
        raw_rows = json.load(f)
    raw_rows.sort(key=lambda r: r["date"])  # arrived in separate fetches; real ts order

    rec = Recorder(FIXTURE_DIR, "real-openf1-9159")

    prov = Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.B)
    # Only fields actually known from the real fetch are set. session_type,
    # circuit_short_name, etc. are left at their honest UNKNOWN/None default -
    # not fetched for real here, so not guessed (Section 9: NULL is correct,
    # a fabricated value is not).
    session = SessionInfo(
        session_id=SESSION_ID, provider=ProviderName.OPENF1,
        provider_session_key="9159", provider_meeting_key="1219",
        year=2023, provenance=prov,
    )
    rec.write(make_envelope(event_type="SESSION_INFO", session_id=SESSION_ID,
                             model=session, source="openf1-historical-fetch",
                             dedupe_key=None))

    for row in raw_rows:
        sample = to_car_sample(row, SESSION_ID)  # the real mapping function
        rec.write(make_envelope(event_type="TELEMETRY_CAR", session_id=SESSION_ID,
                                 model=sample, source="openf1-historical-fetch",
                                 dedupe_key=None, driver_number=sample.driver_number))

    rec.write_meta(
        session_payload={"session_id": SESSION_ID, "provider_session_key": "9159",
                          "provider_meeting_key": "1219"},
        provider_name="openf1-historical",
        capabilities_notes=[
            "Real OpenF1 car_data, session_key=9159, driver 55, 2023-09-15 "
            "(historical, no auth needed). Not synthetic.",
            "SessionInfo intentionally leaves session_type/circuit/etc. as "
            "UNKNOWN/None - not fetched for real, not guessed.",
        ],
    )
    rec.finalize()
    print(f"wrote {rec.seq} real frames to {FIXTURE_DIR / 'real-openf1-9159'}")


if __name__ == "__main__":
    build()
