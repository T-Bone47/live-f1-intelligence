"""Deterministic lap classification (Phase 2).

Classification attaches metadata; raw lap data is NEVER modified or dropped.

Rules (evaluated in order, all flags may attach, class resolves last):
1. DELETED      - tombstone applied via correction ledger.
2. PIT_OUT      - upstream is_pit_out_lap flag OR stint changed on this lap
                  (first lap of a new stint).
3. PIT_IN       - next lap begins a different stint (this lap ends in pits).
4. Flag interference - any YELLOW / DOUBLE_YELLOW / SAFETY_CAR / VSC /
   RED_FLAG period overlapping [lap_start, lap_end).
5. OUTLIER      - duration > outlier_factor * driver's median valid lap in the
                  same stint (default 1.07) when >= 3 valid samples exist.
6. INACCURATE   - upstream explicitly marked the lap inaccurate (FastF1).
Class:
  INVALID if DELETED or RED_FLAG;
  OUTLIER if only outlier;
  otherwise FLYING / PIT_OUT / PIT_IN by pit flags;
  REPRESENTATIVE = FLYING with zero interference/outlier flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.analysis.common.models import LapFlag, LapClass
from app.analysis.race_control import RaceControlState
from app.core.models import Compound


@dataclass
class ClassifiedLap:
    session_id: str
    driver_number: int
    lap_number: int
    started_at: datetime | None
    duration_s: float | None
    sector_times_s: tuple[float | None, float | None, float | None]
    compound: Compound | None = None
    stint_number: int | None = None
    tyre_age: int | None = None
    is_pit_out: bool = False
    is_in_lap: bool = False
    deleted: bool = False
    is_accurate: bool | None = None
    flags: set[str] = field(default_factory=set)
    lap_class: LapClass = LapClass.UNCLASSIFIED
    excluded_reasons: list[str] = field(default_factory=list)

    @property
    def is_representative(self) -> bool:
        return self.lap_class is LapClass.REPRESENTATIVE


class LapClassifier:
    OUTLIER_FACTOR = 1.07
    MIN_SAMPLES_FOR_OUTLIER = 3

    def __init__(self, rc_state: RaceControlState,
                 outlier_factor: float = OUTLIER_FACTOR) -> None:
        self.rc = rc_state
        self.outlier_factor = outlier_factor
        # per (driver, stint) -> list[duration] of clean samples so far
        self._stint_samples: dict[tuple[int, int], list[float]] = {}

    # ---------------------------------------------------------------- fold --

    def classify(self, lap: ClassifiedLap,
                 next_stint_number: int | None = None) -> ClassifiedLap:
        flags: set[str] = set()

        # 1 deletion tombstone
        if getattr(lap, "deleted", False):
            flags.add(LapFlag.DELETED.value)

        # 2/3 pit laps
        if lap.is_pit_out:
            flags.add(LapFlag.PIT_OUT.value)
        if next_stint_number is not None and lap.stint_number is not None \
                and next_stint_number != lap.stint_number:
            flags.add(LapFlag.PIT_IN.value)
        elif getattr(lap, "is_in_lap", False):
            flags.add(LapFlag.PIT_IN.value)

        # 4 flag interference over the lap window
        if lap.started_at is not None and lap.duration_s is not None:
            end = _shift(lap.started_at, lap.duration_s)
            for kind in self.rc.flags_during(lap.started_at, end):
                flags.add({
                    "YELLOW": LapFlag.YELLOW.value,
                    "DOUBLE_YELLOW": LapFlag.DOUBLE_YELLOW.value,
                    "SAFETY_CAR": LapFlag.SAFETY_CAR.value,
                    "VSC": LapFlag.VSC.value,
                    "RED_FLAG": LapFlag.RED_FLAG.value,
                }.get(kind, kind))

        # 5 outlier vs this stint's clean median
        if lap.duration_s is not None and not (flags & {
            LapFlag.DELETED.value, LapFlag.SAFETY_CAR.value, LapFlag.VSC.value,
            LapFlag.RED_FLAG.value, LapFlag.YELLOW.value,
            LapFlag.DOUBLE_YELLOW.value,
        }):
            key = (lap.driver_number, lap.stint_number if lap.stint_number is not None else -1)
            samples = self._stint_samples.get(key, [])
            med = _median(samples)
            if len(samples) >= self.MIN_SAMPLES_FOR_OUTLIER and med and \
                    lap.duration_s > self.outlier_factor * med:
                flags.add(LapFlag.OUTLIER.value)
            else:
                samples.append(lap.duration_s)
                self._stint_samples[key] = samples

        # 6 explicit inaccuracy (FastF1 IsAccurate=False)
        if getattr(lap, "is_accurate", None) is False:
            flags.add(LapFlag.INACCURATE.value)

        lap.flags = flags
        lap.lap_class = self.resolve_class(flags)
        lap.excluded_reasons = sorted(
            f for f in flags if f != LapFlag.INACCURATE.value
        )
        return lap

    @staticmethod
    def resolve_class(flags: set[str]) -> LapClass:
        if LapFlag.DELETED.value in flags or LapFlag.RED_FLAG.value in flags:
            return LapClass.INVALID
        if LapFlag.OUTLIER.value in flags:
            return LapClass.OUTLIER
        if LapFlag.PIT_IN.value in flags:
            return LapClass.PIT_IN
        if LapFlag.PIT_OUT.value in flags:
            return LapClass.PIT_OUT
        if flags & {LapFlag.YELLOW.value, LapFlag.DOUBLE_YELLOW.value,
                    LapFlag.SAFETY_CAR.value, LapFlag.VSC.value}:
            return LapClass.FLYING  # affected but still a flying lap
        return LapClass.REPRESENTATIVE

    # ------------------------------------------------------------ pace use --

    @staticmethod
    def pace_exclusions(lap: ClassifiedLap) -> list[str]:
        """Why this lap is excluded from pace calculations ([] = included)."""
        if lap.duration_s is None:
            return ["NO_TIME"]
        return sorted(lap.flags)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _shift(ts: datetime, seconds: float) -> datetime:
    from datetime import timedelta

    return ts + timedelta(seconds=seconds)
