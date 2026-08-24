"""Weather engine (Phase 2): deterministic trends + threshold events.

Trend definition: OLS slope over the trailing WINDOW samples (default 10)
for each channel, reported in native units per sample (~1 min cadence).
Events fire on documented threshold crossings:
- RAIN_START / RAIN_STOP        (rainfall flag flip)
- TRACK_TEMP_SHIFT / AIR_TEMP_SHIFT   |slope*10| >= 1.0 degC per 10 samples
- HUMIDITY_SHIFT / WIND_SHIFT         |slope*10| >= 5.0 units per 10 samples
No weather *impact* inference in this phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.analysis.common.models import linfit_slope_intercept

WINDOW = 10
TEMP_THRESHOLD_PER_10 = 1.0
HUMIDITY_WIND_THRESHOLD_PER_10 = 5.0


@dataclass
class WeatherState:
    ts: list[datetime] = field(default_factory=list)
    air_temp: list[float] = field(default_factory=list)
    track_temp: list[float] = field(default_factory=list)
    humidity: list[float] = field(default_factory=list)
    pressure: list[float | None] = field(default_factory=list)
    wind_speed: list[float] = field(default_factory=list)
    wind_dir: list[int | None] = field(default_factory=list)
    rainfall: bool | None = None


class WeatherEngine:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.state = WeatherState()

    def fold(self, *, ts: datetime | None, air_temp: float | None,
             track_temp: float | None, humidity: float | None,
             pressure: float | None, rainfall: bool | None,
             wind_direction: int | None, wind_speed: float | None) -> list[dict]:
        events: list[dict] = []
        s = self.state
        if ts is not None:
            s.ts.append(ts)

        def push(series: list, value) -> None:
            if value is not None:
                series.append(value)

        push(s.air_temp, air_temp)
        push(s.track_temp, track_temp)
        push(s.humidity, humidity)
        push(s.pressure, pressure)
        push(s.wind_speed, wind_speed)
        push(s.wind_dir, wind_direction)

        if rainfall is not None and rainfall != s.rainfall:
            if s.rainfall is not None:  # initial state isn't an "event"
                events.append({
                    "event_type": "RAIN_START" if rainfall else "RAIN_STOP",
                    "metrics": {"rainfall": rainfall},
                })
            s.rainfall = rainfall

        for name, series, threshold in (
            ("AIR_TEMP", s.air_temp, TEMP_THRESHOLD_PER_10),
            ("TRACK_TEMP", s.track_temp, TEMP_THRESHOLD_PER_10),
            ("HUMIDITY", s.humidity, HUMIDITY_WIND_THRESHOLD_PER_10),
            ("WIND_SPEED", s.wind_speed, HUMIDITY_WIND_THRESHOLD_PER_10),
        ):
            ev = self._trend_event(name, series, threshold, ts)
            if ev:
                events.append(ev)
        return events

    @staticmethod
    def _trend_event(name: str, series: list[float],
                     threshold: float, ts) -> dict | None:
        tail = series[-WINDOW:]
        if len(tail) < WINDOW:
            return None
        xs = [float(i) for i in range(len(tail))]
        _a, slope, _r2 = linfit_slope_intercept(xs, tail)
        per10 = slope * WINDOW
        if abs(per10) >= threshold:
            direction = "RISING" if slope > 0 else "FALLING"
            return {
                "event_type": f"{name}_SHIFT",
                "metrics": {
                    "direction": direction,
                    f"delta_per_{WINDOW}_samples": round(per10, 3),
                    "current": round(tail[-1], 3),
                },
                "timestamp": ts,
            }
        return None

    # ------------------------------------------------------------- queries --

    def trend(self, channel: str) -> float | None:
        series = {
            "air_temp": self.state.air_temp,
            "track_temp": self.state.track_temp,
            "humidity": self.state.humidity,
            "wind_speed": self.state.wind_speed,
        }.get(channel)
        if not series or len(series) < WINDOW:
            return None
        tail = series[-WINDOW:]
        _a, slope, _r2 = linfit_slope_intercept(
            [float(i) for i in range(len(tail))], tail)
        return round(slope, 4)

    def latest(self) -> dict:
        s = self.state
        out: dict = {}
        for name, series in (("air_temp_c", s.air_temp), ("track_temp_c", s.track_temp),
                             ("humidity_pct", s.humidity), ("wind_speed", s.wind_speed)):
            if series:
                out[name] = series[-1]
        if s.rainfall is not None:
            out["rainfall"] = s.rainfall
        return out
