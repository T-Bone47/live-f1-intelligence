"""Traffic intelligence (Phase 5) - TRAFFIC model with honest UNKNOWNs.

States per driver (computed from latest gaps to nearest cars ahead/behind):

    CLEAR      no car within CLEAR_GAP (3.0 s) either side
    LIGHT      nearest car within [DRS_GAP, CLEAR_GAP]
    HEAVY      nearest car within ACTIVE_GAP (1.5 s)
    FOLLOWING  car ahead within 1.0 s
    FOLLOWED   car behind within 1.0 s
    UNKNOWN    insufficient gap data

Traffic-induced pace loss is reported ONLY with >= MIN_SAMPLES laps in both
traffic and clean conditions within the same stint; recovery = pace returning
to clean median after a HEAVY/FOLLOWING episode ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.analysis.common.models import Confidence, mean
from app.analysis.confidence import assess_confidence


class TrafficState(str, Enum):
    CLEAR = "CLEAR"
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"
    FOLLOWING = "FOLLOWING"
    FOLLOWED = "FOLLOWED"
    UNKNOWN = "UNKNOWN"


CLEAR_GAP = 3.0
LIGHT_GAP = 1.5
FOLLOW_GAP = 1.0
MIN_SAMPLES_FOR_LOSS = 3


@dataclass
class TrafficAssessment:
    state: TrafficState
    gap_ahead_s: float | None
    gap_behind_s: float | None
    confidence: Confidence


class TrafficModel:
    def __init__(self) -> None:
        # driver -> list of lap records while in traffic/clean for pace loss
        self._laps: dict[int, list[tuple[str, float]]] = {}

    def classify(self, *, gap_ahead_s: float | None,
                 gap_behind_s: float | None,
                 symbolic_ahead: bool = False,
                 has_any_gap_data: bool = True) -> TrafficAssessment:
        if not has_any_gap_data or (gap_ahead_s is None and gap_behind_s is None):
            return TrafficAssessment(TrafficState.UNKNOWN, gap_ahead_s,
                                     gap_behind_s, Confidence.NONE)
        ahead = gap_ahead_s
        behind = gap_behind_s
        if symbolic_ahead:
            ahead = 999.0   # lapped field: treat as clear rather than fake-close

        if ahead is not None and ahead <= FOLLOW_GAP:
            state = TrafficState.FOLLOWING
        elif behind is not None and behind <= FOLLOW_GAP:
            state = TrafficState.FOLLOWED
        elif (ahead is not None and ahead <= LIGHT_GAP) or \
             (behind is not None and behind <= LIGHT_GAP):
            state = TrafficState.HEAVY
        elif (ahead is not None and ahead <= CLEAR_GAP) or \
             (behind is not None and behind <= CLEAR_GAP):
            state = TrafficState.LIGHT
        else:
            state = TrafficState.CLEAR

        conf = Confidence.HIGH if (ahead is not None and behind is not None) \
            else Confidence.MEDIUM
        return TrafficAssessment(state, gap_ahead_s, gap_behind_s, conf)

    # ------------------------------------------------------- pace loss ------

    def fold_lap(self, driver_number: int, traffic_state: TrafficState,
                 duration_s: float) -> None:
        bucket = "CLEAN" if traffic_state is TrafficState.CLEAR else \
            ("TRAFFIC" if traffic_state in (TrafficState.HEAVY,
                                            TrafficState.FOLLOWING) else "OTHER")
        self._laps.setdefault(driver_number, []).append((bucket, duration_s))
        if len(self._laps[driver_number]) > 200:
            self._laps[driver_number].pop(0)

    def pace_loss(self, driver_number: int) -> tuple[float | None, int, int]:
        rows = self._laps.get(driver_number, [])
        clean = [d for b, d in rows if b == "CLEAN"]
        traf = [d for b, d in rows if b == "TRAFFIC"]
        if len(clean) < MIN_SAMPLES_FOR_LOSS or len(traf) < MIN_SAMPLES_FOR_LOSS:
            return None, len(traf), len(clean)
        cm, tm = mean(clean), mean(traf)
        if cm is None or tm is None:
            return None, len(traf), len(clean)
        return round(tm - cm, 3), len(traf), len(clean)

    def recovered_after_traffic(self, driver_number: int,
                                recent_clean_laps: list[float],
                                clean_baseline: float | None) -> bool | None:
        """TRUE when >=2 recent clean laps within 0.3 s of stint clean median."""
        if clean_baseline is None or len(recent_clean_laps) < 2:
            return None
        return all(abs(v - clean_baseline) <= 0.3 for v in recent_clean_laps[-2:])
