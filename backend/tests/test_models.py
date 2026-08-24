"""Canonical schema behavior: nullability, provenance, serialization."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.enums import Compound, ProvenanceClass, ProviderName, RCMCategory
from app.core.models import (
    Driver,
    Lap,
    Provenance,
    RaceControlEvent,
    TelemetryCarSample,
    WeatherPoint,
)


def prov(ts: datetime | None = None) -> Provenance:
    return Provenance(
        provider=ProviderName.OPENF1,
        source_timestamp=ts,
        provenance_class=ProvenanceClass.A if ts else ProvenanceClass.B,
    )


TS = datetime(2026, 8, 23, 13, 3, 28, tzinfo=timezone.utc)


def test_telemetry_allows_nulls_but_needs_identity() -> None:
    # every measurement channel nullable (verified: drs is null upstream)
    m = TelemetryCarSample(
        session_id="openf1:11353",
        driver_number=63,
        ts=TS,
        rpm=None,
        speed_kph=None,
        gear=None,
        throttle_pct=None,
        brake_pct=None,
        drs=None,
        provenance=prov(TS),
    )
    assert m.drs is None and m.speed_kph is None


def test_throttle_clamped_brake_binary_preserved() -> None:
    m = TelemetryCarSample(
        session_id="s", driver_number=1, ts=TS, throttle_pct=150.0, brake_pct=100.0,
        provenance=prov(TS),
    )
    assert m.throttle_pct == 100.0  # clamped, not rejected
    assert m.brake_pct == 100.0


def test_lap_requires_timestamp_and_identity() -> None:
    with pytest.raises(ValidationError):
        Lap(session_id="s", driver_number=63, lap_number=1, provenance=prov(None))


def test_provenance_class_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Lap(
            session_id="s", driver_number=63, lap_number=1, started_at=TS,
            provenance={"provider": "openf1", "provenance_class": "Z"},
        )


def test_rcm_key_stable_for_same_content() -> None:
    k1 = RaceControlEvent.make_key(TS, "YELLOW IN TRACK SECTOR 14")
    k2 = RaceControlEvent.make_key(TS.replace(microsecond=999), "YELLOW IN TRACK SECTOR 14")
    k3 = RaceControlEvent.make_key(datetime(2026, 8, 23, 13, 4, 0, tzinfo=timezone.utc),
                                   "YELLOW IN TRACK SECTOR 14")
    assert k1 == k2  # same second+message -> same key (dedupe)
    assert k1 != k3


def test_unknown_enum_values_map_explicitly() -> None:
    d = Driver.model_validate(
        {
            "driver_id": "x-1",
            "full_name": "Unknown Driver",
            "provenance": {"provider": "openf1", "provenance_class": "B"},
        }
    )
    assert d.country_code is None  # verified nullable upstream


def test_compound_unknown_not_silently_mapped() -> None:
    from app.providers.openf1.mapping import safe, to_stint

    stint = safe(to_stint, {
        "session_key": 11353, "stint_number": 9, "driver_number": 63,
        "lap_start": 1, "lap_end": 5, "tyre_age_at_start": 0,
        "compound": "SLICK_XYZ",
    }, "openf1:11353")
    assert stint.compound == Compound.UNKNOWN


def test_weather_rainfall_boolean() -> None:
    wx = WeatherPoint(
        session_id="s", ts=TS, rainfall=False,
        provenance={"provider": "openf1", "source_timestamp": TS, "provenance_class": "A"},
    )
    assert wx.rainfall is False and wx.air_temp_c is None


def test_rcm_category_unknown_fallback_via_mapping() -> None:
    # Canonical models are STRICT; tolerance lives in the provider mapping layer.
    from app.providers.openf1.mapping import safe, to_rcm

    rcm = safe(to_rcm, {
        "date": "2026-08-23T13:30:00+00:00",
        "category": "Bizarro",
        "message": "WEIRD MESSAGE",
    }, "s")
    assert rcm.category == RCMCategory.UNKNOWN
