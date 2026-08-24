"""Gap engine (Phase 2): gap-to-ahead/behind views, closing rate, trend.

Closing rate (documented definition):
    For a pair (ahead A, behind B) we track B's interval to A sampled once per
    lap (latest sample of each lap). Over a window of W samples:

        closing_rate_s_per_lap = (gap_latest - gap_first) / (n_samples - 1)

    Negative == closing. Timestamp-based rates are NOT mixed in: lap-sampled
    values are the stable canonical unit (fuel/track evolution drift cancels).

Symbolic gaps ('+1 LAP') never enter numeric math; pairs involving them are
reported with numeric=None.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.common.models import mean


@dataclass
class PairGapState:
    ahead: int
    behind: int
    samples: list[tuple[int | None, float]] = field(default_factory=list)  # (lap, gap)

    def closing_rate(self, window: int = 3) -> float | None:
        rows = self.samples[-window:]
        if len(rows) < 2:
            return None
        first_gap = rows[0][1]
        last_gap = rows[-1][1]
        n = len(rows)
        return round((last_gap - first_gap) / (n - 1), 4)

    def trend(self) -> str:
        rate = self.closing_rate()
        if rate is None:
            return "UNKNOWN"
        if rate <= -0.15:
            return "CLOSING_FAST"
        if rate < -0.05:
            return "CLOSING"
        if rate > 0.15:
            return "OPENING_FAST"
        if rate > 0.05:
            return "OPENING"
        return "STABLE"


class GapEngine:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.pairs: dict[tuple[int, int], PairGapState] = {}
        self.latest_gaps: dict[int, float | None] = {}       # num -> interval_s
        self.symbolic: dict[int, str | None] = {}             # num -> '+N LAP'

    def fold_interval(self, driver_number: int, gap_to_leader_s: float | None,
                      interval_s: float | None, gap_raw: str | None,
                      interval_raw: str | None, lap: int | None,
                      car_ahead: int | None = None) -> None:
        """Interval semantics: driver's gap to the car directly ahead."""
        if gap_raw:
            self.symbolic[driver_number] = gap_raw
        elif isinstance(gap_to_leader_s, float):
            self.latest_gaps.setdefault(driver_number, gap_to_leader_s)

        if isinstance(interval_s, float):
            self.latest_gaps[driver_number] = interval_s
            if car_ahead is not None:
                key = (min(car_ahead, driver_number), max(car_ahead, driver_number))
                # store directionally: (ahead, behind) normalized below
                state = self._pair(car_ahead, driver_number)
                state.samples.append((lap, interval_s))
                if len(state.samples) > 60:
                    state.samples.pop(0)
        elif interval_raw:
            self.symbolic[driver_number] = interval_raw

    def _pair(self, ahead: int, behind: int) -> PairGapState:
        key = (ahead, behind)
        if key not in self.pairs:
            self.pairs[key] = PairGapState(ahead=ahead, behind=behind)
        return self.pairs[key]

    def closing_rate(self, ahead: int, behind: int, window: int = 3) -> float | None:
        st = self.pairs.get((ahead, behind))
        return st.closing_rate(window) if st else None

    def gap_trend(self, ahead: int, behind: int) -> str:
        st = self.pairs.get((ahead, behind))
        return st.trend() if st else "UNKNOWN"

    def neighbors_by_position(self, positions: dict[int, int]) -> dict[int, tuple[int | None, int | None]]:
        """Return {driver: (car_ahead, car_behind)} from position map."""
        order = sorted(positions.items(), key=lambda t: t[1])
        out: dict[int, tuple[int | None, int | None]] = {}
        for i, (num, _pos) in enumerate(order):
            ahead = order[i - 1][0] if i else None
            behind = order[i + 1][0] if i + 1 < len(order) else None
            out[num] = (ahead, behind)
        return out
