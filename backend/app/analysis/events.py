"""Significant event engine (Phase 2): deterministic detection + dedupe.

Event keys (EVENT_DEFINITIONS.md normative) - identity components per type:

    PURPLE_SECTOR          sid|PURPLE_SECTOR|{driver}|S{i}|L{lap}
    PERSONAL_BEST_LAP      sid|PERSONAL_BEST_LAP|{driver}|L{lap}
    FASTEST_LAP_CHANGE     sid|FASTEST_LAP_CHANGE|L{lap}
    POSITION_CHANGE        sid|POSITION_CHANGE|{driver}|L{lap}|{from}->{to}
    PACE_CHANGE / PACE_DROP    ...|{driver}|W{window}|BUCKET{lap//3}
    TYRE_DEGRADATION_CHANGE    ...|{driver}|STINT{n}|SIGN{+/-}
    BATTLE_STARTED         ...|{ahead}v{behind}|L{start_lap}
    BATTLE_ESCALATED       ...|{ahead}v{behind}|TO_{state}
    OVERTAKE               ...|{winner}v{loser}|L{lap}
    PIT_STOP               ...|{driver}|TS{ts_epoch}
    PIT_WINDOW             ...|{driver}|FROM{open_lap}
    WEATHER_CHANGE         ...|{metric}|{direction}|BUCKET{sample_idx//10}
    SAFETY_CAR/VSC/RED_FLAG    ...|{type}|RCM{rcm_key or ts}
    SESSION_STATE_CHANGE   ...|{from}_{to}|N{transition_index}

Dedupe: identical key within the session lifetime is suppressed by
EventDeduplicator; bucketed keys allow legitimate recurrence without spam.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.battles import Battle, BattleState
from app.analysis.common.dedup import EventDeduplicator
from app.analysis.common.models import (
    CALC_VERSION,
    Confidence,
    DerivedProvenance,
    IntelligenceEvent,
    Severity,
)
from app.analysis.sectors import SectorClassification


class SignificantEventEngine:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.dedup = EventDeduplicator()
        self.events: list[IntelligenceEvent] = []
        self.listeners: list = []   # callables(IntelligenceEvent) notified on emit

    # ------------------------------------------------------------- emit -----

    def _emit(self, event_type: str, identity: str, *, ts: datetime,
              drivers: tuple[int, ...] = (), severity: Severity = Severity.INFO,
              metrics: dict | None = None, evidence: tuple[str, ...] = (),
              prediction: bool = False,
              confidence: Confidence = Confidence.MEDIUM) -> IntelligenceEvent | None:
        key = EventDeduplicator.build_key(self.session_id, event_type, identity)
        if self.dedup.is_duplicate(key):
            return None
        ev = IntelligenceEvent(
            event_key=key,
            event_type=event_type,
            session_id=self.session_id,
            timestamp=ts or datetime.now(timezone.utc),
            driver_numbers=drivers,
            severity=severity,
            metrics=metrics or {},
            evidence=evidence,
            provenance=DerivedProvenance(
                session_id=self.session_id,
                calculated_at=datetime.now(timezone.utc),
                confidence=confidence,
            ),
            prediction=prediction,
        )
        self.events.append(ev)
        for cb in self.listeners:
            try:
                cb(ev)
            except Exception:  # noqa: BLE001 - listener isolation
                pass
        return ev

    # ------------------------------------------------- generic (Phase 5) ----

    def custom(self, event_type: str, identity: str, *, ts: datetime,
               drivers: tuple[int, ...] = (),
               severity: Severity = Severity.INFO,
               metrics: dict | None = None,
               evidence: tuple[str, ...] = (),
               prediction: bool = False,
               assumptions: list[str] | None = None) -> IntelligenceEvent | None:
        """Generic Phase-5 emitter; metrics carry assumptions when provided."""
        m = dict(metrics or {})
        if assumptions:
            m["assumptions"] = assumptions
        return self._emit(event_type, identity, ts=ts, drivers=drivers,
                          severity=severity, metrics=m, evidence=evidence,
                          prediction=prediction)

    # ----------------------------------------------------------- sectors ----

    def sector_classified(self, c: SectorClassification, driver_number: int,
                          lap_number: int, ts: datetime) -> IntelligenceEvent | None:
        if c.classification == "PURPLE":
            return self._emit(
                "PURPLE_SECTOR", f"{driver_number}|S{c.sector_index}|L{lap_number}",
                ts=ts, drivers=(driver_number,), severity=Severity.NOTABLE,
                metrics={"sector": c.sector_index, "time_s": c.time_s},
                evidence=(f"sector {c.sector_index} time {c.time_s}s on lap {lap_number}",))
        if c.improved_personal_best and c.classification == "GREEN":
            return self._emit(
                "PERSONAL_BEST", f"SECTOR|{driver_number}|S{c.sector_index}|L{lap_number}",
                ts=ts, drivers=(driver_number,),
                metrics={"sector": c.sector_index, "time_s": c.time_s,
                         "delta_to_pb_s": round(c.delta_to_pb_s, 4)
                         if c.delta_to_pb_s is not None else None})
        return None

    # --------------------------------------------------------------- laps ----

    def lap_completed(self, *, driver_number: int, lap_number: int,
                      duration_s: float | None, personal_best: bool,
                      session_best_change: bool, is_first_sb: bool, ts: datetime) -> list:
        out = []
        if personal_best and not session_best_change:
            ev = self._emit(
                "PERSONAL_BEST_LAP",
                f"{driver_number}|L{lap_number}", ts=ts, drivers=(driver_number,),
                metrics={"lap": lap_number, "duration_s": duration_s})
            if ev:
                out.append(ev)
        if session_best_change and not is_first_sb:
            ev = self._emit(
                "FASTEST_LAP_CHANGE",
                f"L{lap_number}", ts=ts, drivers=(driver_number,),
                severity=Severity.IMPORTANT,
                metrics={"lap": lap_number, "duration_s": duration_s})
            if ev:
                out.append(ev)
        return out

    def position_changed(self, driver_number: int, old: int | None, new: int | None,
                         lap: int | None, ts: datetime) -> IntelligenceEvent | None:
        if old is None or new is None or old == new:
            return None
        notable = min(old, new) <= 10  # involves a top-10 position
        return self._emit(
            "POSITION_CHANGE",
            f"{driver_number}|L{lap}|{old}->{new}", ts=ts,
            drivers=(driver_number,),
            severity=Severity.NOTABLE if notable else Severity.INFO,
            metrics={"from": old, "to": new, "lap": lap})

    # --------------------------------------------------------------- pace ----

    def pace_shift(self, driver_number: int, slope_s_per_lap: float,
                   lap: int | None, ts: datetime) -> IntelligenceEvent | None:
        if abs(slope_s_per_lap) < 0.3:
            return None
        etype = "PACE_DROP" if slope_s_per_lap > 0 else "PACE_CHANGE"
        return self._emit(
            etype, f"{driver_number}|W5|BUCKET{(lap or 0) // 3}",
            ts=ts, drivers=(driver_number,),
            severity=Severity.NOTABLE if abs(slope_s_per_lap) < 1.0 else Severity.IMPORTANT,
            metrics={"slope_s_per_lap": round(slope_s_per_lap, 4), "window": 5})

    def degradation_change(self, driver_number: int, stint_number: int,
                           rate_s_per_lap: float, r2: float, n: int,
                           confidence: str, ts: datetime) -> IntelligenceEvent | None:
        sign = "PLUS" if rate_s_per_lap >= 0 else "MINUS"
        sev = Severity.NOTABLE if abs(rate_s_per_lap) < 0.25 else Severity.IMPORTANT
        return self._emit(
            "TYRE_DEGRADATION_CHANGE",
            f"{driver_number}|STINT{stint_number}|SIGN{sign}",
            ts=ts, drivers=(driver_number,), severity=sev,
            metrics={
                "estimated_degradation_s_per_lap": round(rate_s_per_lap, 4),
                "r_squared": round(r2, 3), "samples": n, "confidence": confidence,
                "label": "ESTIMATED DEGRADATION - not official data",
            },
            prediction=True)

    # ------------------------------------------------------------- battle ----

    def battle_update(self, b: Battle, ts: datetime) -> IntelligenceEvent | None:
        pair = f"{b.ahead}v{b.behind}"
        if b.state in (BattleState.DRS_RANGE, BattleState.ACTIVE_BATTLE) and \
                b.samples_in_state == 1:
            return self._emit("BATTLE_STARTED", f"{pair}|L{b.started_lap}", ts=ts,
                              drivers=(b.ahead, b.behind), severity=Severity.NOTABLE,
                              metrics={"state": b.state.value,
                                       "min_gap_s": b.min_gap_s})
        if b.state is BattleState.OVERTAKE:
            winner, loser = b.behind, b.ahead  # behind passed ahead
            return self._emit("OVERTAKE", f"{winner}v{loser}|L{b.started_lap}",
                              ts=ts, drivers=(b.ahead, b.behind),
                              severity=Severity.IMPORTANT,
                              metrics={"state": "OVERTAKE"})
        if b.state is BattleState.SEPARATING:
            return self._emit("BATTLE_ESCALATED" if False else "BATTLE_SEPARATED",
                              f"{pair}|SEP|L{(b.started_lap or 0)}",
                              ts=ts, drivers=(b.ahead, b.behind),
                              metrics={"last_gap_s": b.last_gap_s})
        return None

    def battle_escalated(self, b: Battle, new_state: BattleState, ts: datetime):
        return self._emit("BATTLE_ESCALATED",
                          f"{b.ahead}v{b.behind}|TO_{new_state.value}",
                          ts=ts, drivers=(b.ahead, b.behind),
                          severity=Severity.NOTABLE,
                          metrics={"state": new_state.value,
                                   "gap_s": b.last_gap_s})

    # ---------------------------------------------------------------- pit ----

    def pit_stop(self, driver_number: int, ts: datetime,
                 lane_duration_s: float | None) -> IntelligenceEvent | None:
        ident = f"{driver_number}|TS{int(ts.timestamp())}"
        return self._emit("PIT_STOP", ident, ts=ts, drivers=(driver_number,),
                          severity=Severity.NOTABLE,
                          metrics={"lane_duration_s": lane_duration_s})

    def pit_window(self, driver_number: int, window: tuple[int, int],
                   compound: str, tyre_age: int, ts: datetime):
        return self._emit("PIT_WINDOW", f"{driver_number}|FROM{window[0]}",
                          ts=ts, drivers=(driver_number,), severity=Severity.INFO,
                          metrics={"window_laps": list(window),
                                   "compound": compound, "tyre_age": tyre_age},
                          prediction=True)

    # ------------------------------------------------------------- weather ---

    def weather_events(self, raw_events: list[dict], default_ts: datetime):
        out = []
        for e in raw_events:
            metric = e["event_type"].split("_")[0]
            direction = e.get("metrics", {}).get("direction", "FLAG")
            idx = len(self.events)
            ev = self._emit("WEATHER_CHANGE",
                            f"{metric}|{direction}|BUCKET{idx // 10}",
                            ts=e.get("timestamp") or default_ts,
                            severity=Severity.NOTABLE,
                            metrics=e.get("metrics", {}))
            if ev:
                out.append(ev)
        return out

    # -------------------------------------------------------- race control --

    def race_control_event(self, event_type: str, identity: str, message: str,
                           ts: datetime):
        severity = {"RED_FLAG": Severity.CRITICAL}.get(event_type, Severity.IMPORTANT)
        return self._emit(event_type, identity, ts=ts, severity=severity,
                          metrics={"message": message[:160]})

    def session_state_changed(self, from_phase: str, to_phase: str,
                              index: int, ts: datetime):
        return self._emit("SESSION_STATE_CHANGE",
                          f"{from_phase}_{to_phase}|N{index}", ts=ts,
                          severity=Severity.IMPORTANT,
                          metrics={"from": from_phase, "to": to_phase})
