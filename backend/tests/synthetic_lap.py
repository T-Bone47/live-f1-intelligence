"""SYNTHETIC lap generator for Phase 10.4 unit tests - never evidence.

Builds a Lap + OpenF1-shaped TelemetryCarSample list from a distance-based
profile, sampled at a fixed rate like the real feed (~3.7 Hz). It exists to
pin detector mechanics with KNOWN ground truth (e.g. "B brakes 20 m later");
real-data behaviour is tested separately against the Singapore fixture.

Profile semantics (all positions in metres along the lap):
- speed_knots: [(s, kph), ...] linearly interpolated in distance;
- brake: [(s0, s1), ...] intervals with brake 100, else 0 (the real feed is
  binary 0/100 - verified in scripts/fixtures/real-openf1-pair);
- throttle_knots: [(s, pct), ...] linearly interpolated, rounded to int;
- gear_knots: [(s, gear), ...] step function (value holds from s on);
- drs: [(s0, s1, code), ...] else code 8.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.enums import ProvenanceClass, ProviderName
from app.core.models import Lap, Provenance, TelemetryCarSample

SID = "synthetic:10.4"


@dataclass
class Profile:
    length_m: float
    speed_knots: list[tuple[float, float]]
    brake: list[tuple[float, float]] = field(default_factory=list)
    throttle_knots: list[tuple[float, float]] = field(default_factory=lambda: [(0.0, 100.0)])
    gear_knots: list[tuple[float, int]] = field(default_factory=lambda: [(0.0, 8)])
    drs: list[tuple[float, float, int]] = field(default_factory=list)
    sector_lines_m: tuple[float, float] | None = None


def _lerp(knots, s):
    xs = [k[0] for k in knots]
    i = bisect.bisect_right(xs, s)
    if i == 0:
        return knots[0][1]
    if i >= len(knots):
        return knots[-1][1]
    (x0, y0), (x1, y1) = knots[i - 1], knots[i]
    return y0 + (s - x0) / (x1 - x0) * (y1 - y0)


def _step(knots, s):
    xs = [k[0] for k in knots]
    i = bisect.bisect_right(xs, s)
    return knots[max(i - 1, 0)][1]


def _prov() -> Provenance:
    return Provenance(provider=ProviderName.OPENF1, provenance_class=ProvenanceClass.B)


def make_lap(profile: Profile, driver: int, lap_number: int = 1,
             t0: datetime | None = None, hz: float = 3.7,
             phase_s: float = 0.0) -> tuple[Lap, list[TelemetryCarSample]]:
    """Integrate time along the profile (0.25 m steps), then sample at hz.

    phase_s shifts the sampling clock (0 <= phase_s < 1/hz): the first sample
    is at lap start + phase_s, like a real feed whose samples do not line up
    with the timing line.
    """
    t0 = t0 or datetime(2026, 1, 1, 12, tzinfo=UTC)
    ds = 0.25
    s_grid = [0.0]
    t_grid = [0.0]
    s = 0.0
    while s < profile.length_m:
        s1 = min(s + ds, profile.length_m)
        v0 = _lerp(profile.speed_knots, s) / 3.6
        v1 = _lerp(profile.speed_knots, s1) / 3.6
        t_grid.append(t_grid[-1] + 2 * (s1 - s) / (v0 + v1))
        s_grid.append(s1)
        s = s1
    duration = t_grid[-1]

    def s_at(t):
        i = bisect.bisect_right(t_grid, t)
        if i >= len(t_grid):
            return s_grid[-1]
        return s_grid[i - 1] + (t - t_grid[i - 1]) / (t_grid[i] - t_grid[i - 1]) * (
            s_grid[i] - s_grid[i - 1])

    samples = []
    k = 0
    while True:
        t = phase_s + k / hz
        if t > duration:
            break
        pos = s_at(t)
        brake = 100.0 if any(a <= pos < b for a, b in profile.brake) else 0.0
        drs = next((c for a, b, c in profile.drs if a <= pos < b), 8)
        samples.append(TelemetryCarSample(
            session_id=SID, driver_number=driver, ts=t0 + timedelta(seconds=t),
            speed_kph=round(_lerp(profile.speed_knots, pos)),
            throttle_pct=float(round(_lerp(profile.throttle_knots, pos))),
            brake_pct=brake, gear=_step(profile.gear_knots, pos), drs=drs,
            rpm=10000, provenance=_prov()))
        k += 1

    sectors: list[float | None] = [None, None, None]
    if profile.sector_lines_m:
        def t_at(pos):
            i = bisect.bisect_left(s_grid, pos)
            return t_grid[min(i, len(t_grid) - 1)]
        l1, l2 = profile.sector_lines_m
        s1_t, s2_t = round(t_at(l1), 3), round(t_at(l2) - t_at(l1), 3)
        sectors = [s1_t, s2_t, round(duration - s1_t - s2_t, 3)]
    lap = Lap(session_id=SID, driver_number=driver, lap_number=lap_number, started_at=t0,
              duration_s=round(duration, 3), sector1_s=sectors[0], sector2_s=sectors[1],
              sector3_s=sectors[2], is_pit_out_lap=False, provenance=_prov())
    return lap, samples


def two_corner_profile(**over) -> Profile:
    """A 2,000 m lap: straight, corner 1 (brake 500-600 m, 300->100 kph),
    straight, corner 2 (brake 1300-1380 m, 300->150 kph), straight."""
    base = {
        "length_m": 2000.0,
        "speed_knots": [(0, 280), (500, 300), (600, 100), (650, 100), (900, 290),
                     (1300, 300), (1380, 150), (1420, 150), (1650, 290), (2000, 295)],
        "brake": [(500, 600), (1300, 1380)],
        "throttle_knots": [(0, 100), (495, 100), (500, 0), (620, 0), (640, 30), (720, 100),
                        (1295, 100), (1300, 0), (1400, 0), (1420, 40), (1500, 100),
                        (2000, 100)],
        "gear_knots": [(0, 8), (520, 6), (560, 4), (590, 3), (700, 4), (760, 5), (820, 6),
                    (870, 7), (950, 8), (1320, 6), (1360, 5), (1450, 6), (1550, 7),
                    (1650, 8)],
        "sector_lines_m": (800.0, 1500.0),
    }
    base.update(over)
    return Profile(**base)
