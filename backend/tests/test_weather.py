"""Coverage for WeatherEngine.latest()'s output contract.

Nothing previously exercised latest() directly, so the frontend-facing key
names it emits were never checked against what components actually consume.
Two bugs lived here silently: the wind-speed key was named `wind_speed`
(ambiguous unit, and not what any consumer reads) instead of the canonical
`wind_speed_mps`, and wind direction was folded into state (`wind_dir`) but
never surfaced in latest() at all.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.weather import WeatherEngine


def _fold(engine: WeatherEngine, **overrides) -> list[dict]:
    defaults = dict(
        ts=datetime.now(timezone.utc),
        air_temp=22.0,
        track_temp=31.0,
        humidity=55.0,
        pressure=1013.0,
        rainfall=False,
        wind_direction=210,
        wind_speed=3.4,
    )
    defaults.update(overrides)
    return engine.fold(**defaults)


def test_latest_emits_wind_speed_mps_not_bare_wind_speed():
    engine = WeatherEngine("openf1:11353")
    _fold(engine, wind_speed=3.4)

    latest = engine.latest()

    assert latest["wind_speed_mps"] == 3.4
    assert "wind_speed" not in latest


def test_latest_surfaces_wind_direction_deg():
    engine = WeatherEngine("openf1:11353")
    _fold(engine, wind_direction=210)

    latest = engine.latest()

    assert latest["wind_direction_deg"] == 210


def test_latest_omits_wind_direction_deg_when_never_folded():
    engine = WeatherEngine("openf1:11353")
    _fold(engine, wind_direction=None)

    latest = engine.latest()

    assert "wind_direction_deg" not in latest


def test_latest_still_reports_rainfall_boolean():
    engine = WeatherEngine("openf1:11353")
    _fold(engine, rainfall=True)

    latest = engine.latest()

    assert latest["rainfall"] is True
