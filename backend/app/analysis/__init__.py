"""AnalysisEngine (Phase 2 facade): canonical envelopes -> intelligence.

- Consumes ONLY canonical envelopes (provider-independent by construction).
- Incremental: each event updates cached state; no session-wide recompute.
- Deterministic: same input stream => same snapshot/events (backtested).
- Opt-in at runtime: scripts subscribe this engine when F1_ANALYZE=1.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.analysis import strategy as strat_mod
from app.analysis.battles import BattleDetector, BattleState
from app.analysis.common.models import CALC_VERSION, DerivedProvenance, Severity
from app.analysis.events import SignificantEventEngine
from app.analysis.gaps import GapEngine
from app.analysis.laps import ClassifiedLap, LapClassifier
from app.analysis.pace import PaceEngine
from app.analysis.race_control import RaceControlState
from app.analysis.sectors import SectorEngine
from app.analysis.session import SessionContext
from app.analysis.snapshot import SessionSnapshot, SnapshotBuilder
from app.analysis.timing import TimingEngine
from app.analysis.tyres import StintEngine
from app.analysis.weather import WeatherEngine

log = logging.getLogger(__name__)

PACE_SHIFT_THRESHOLD = 0.3  # s/lap slope to raise PACE_CHANGE/PACE_DROP


def is_race_like(profile) -> bool:  # noqa: ANN001 Profile|None
    from app.analysis.session import Profile as _P

    return profile in (_P.RACE, _P.SPRINT)


class AnalysisEngine:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.ctx = SessionContext(session_id=session_id)
        self.rc = RaceControlState()
        self.classifier = LapClassifier(self.rc)
        self.timing = TimingEngine(session_id)
        self.sectors = SectorEngine(session_id)
        self.pace = PaceEngine(session_id)
        self.stints = StintEngine(session_id)
        self.gaps = GapEngine(session_id)
        self.battles = BattleDetector()
        self.weather = WeatherEngine(session_id)
        self.strategy = strat_mod.StrategyPrimitives(session_id)
        self.sig = SignificantEventEngine(session_id)
        self.builder = SnapshotBuilder(
            timing=self.timing, sectors=self.sectors, pace=self.pace,
            stints=self.stints, gaps=self.gaps, battles=self.battles,
            rc=self.rc, weather=self.weather,
        )
        self._corr_open: dict[tuple[int, int], bool] = {}   # (driver, lap)->deleted
        self._state_transition_count = 0

    # ------------------------------------------------------------- intake ----

    # Context ordering: laps/sectors/intervals depend on stint + race-control
    # context which providers may deliver late (verified in real recordings).
    # We defer those types until a primer arrives or the buffer caps out -
    # deterministic, bounded, and identical for live and replay.
    PRIMER_TYPES = {"TyreStint", "PitStop"}
    DEFERRED_TYPES = {"Lap", "SectorTime"}
    MAX_DEFERRED = 20_000

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.ctx = SessionContext(session_id=session_id)
        self.rc = RaceControlState()
        self.classifier = LapClassifier(self.rc)
        self.timing = TimingEngine(session_id)
        self.sectors = SectorEngine(session_id)
        self.pace = PaceEngine(session_id)
        self.stints = StintEngine(session_id)
        self.gaps = GapEngine(session_id)
        self.battles = BattleDetector()
        self.weather = WeatherEngine(session_id)
        self.strategy = strat_mod.StrategyPrimitives(session_id)
        self.sig = SignificantEventEngine(session_id)
        self.builder = SnapshotBuilder(
            timing=self.timing, sectors=self.sectors, pace=self.pace,
            stints=self.stints, gaps=self.gaps, battles=self.battles,
            rc=self.rc, weather=self.weather,
        )
        self._corr_open: dict[tuple[int, int], bool] = {}   # (driver, lap)->deleted
        self._state_transition_count = 0
        self._primed = False
        self._deferred: list = []

        # ---- Phase 5 deterministic intelligence layers ----
        from app.analysis.racepace2 import RacePace2
        from app.analysis.traffic import TrafficModel
        from app.analysis.strategy2 import StrategyEngine2
        from app.analysis.drs import DRSAnalyzer
        from app.analysis.sessions_intel import QualifyingIntel, PracticeIntel

        self.racepace2 = RacePace2(session_id)
        self.traffic_model = TrafficModel()
        self.strategy2 = StrategyEngine2()
        self.drs = DRSAnalyzer(provider_supports_drs=False)   # OpenF1 path; SignalR flips later
        self.drivers_meta: dict[int, dict] = {}               # num -> {team_id, team_name}
        self.quali = QualifyingIntel()
        self.practice = PracticeIntel()
        self._last_window5: dict[int, float | None] = {}
        self._field_spread_ticks = 0

    def process_envelope(self, envelope) -> list:   # noqa: ANN001 Envelope
        info = envelope.payload.get("model", {})
        mtype = info.get("type")
        if not self._primed:
            if mtype in self.DEFERRED_TYPES:
                if len(self._deferred) < self.MAX_DEFERRED:
                    self._deferred.append(envelope)
                    return []
                # buffer full without context: flush and proceed unprimed
                self.flush_deferred()
                return self._dispatch(envelope)
            if mtype in self.PRIMER_TYPES:
                self._primed = True
                produced = []
                for pending in self._deferred:
                    produced.extend(self._dispatch(pending))
                self._deferred.clear()
                produced.extend(self._dispatch(envelope))
                return [e for e in produced if e is not None]
        return self._dispatch(envelope)

    def flush_deferred(self) -> None:
        """Force-process buffered context-dependent events (end of stream)."""
        self._primed = True
        for pending in self._deferred:
            self._dispatch(pending)
        self._deferred.clear()

    def _dispatch(self, envelope) -> list:  # noqa: ANN001 Envelope
        info = envelope.payload.get("model", {})
        mtype = info.get("type")
        handler = _HANDLERS.get(mtype)
        if not handler:
            return []
        try:
            model = _rebuild(mtype, info)
            return [e for e in handler(self, model, envelope) if e is not None]
        except Exception as exc:  # noqa: BLE001 - analysis never kills ingest
            log.warning("analysis skipped %s (%s)", mtype, exc)
            return []

    # ------------------------------------------------------------- models ----

    def on_session(self, s, envelope):  # noqa: ANN001
        self.ctx.session_type = s.session_type
        return []

    def on_driver(self, d, envelope):  # noqa: ANN001 Driver
        if envelope.driver_number is not None:
            team = d.team.display_name if d.team else None
            self.drivers_meta[envelope.driver_number] = {
                "team_id": d.team.team_id if d.team else None,
                "team_name": team,
                "full_name": d.full_name,
                "acronym": d.name_acronym,
            }
            if d.team:
                self.racepace2.set_team(envelope.driver_number, d.team.team_id)
        return []

    def on_rcm(self, rcm, envelope):
        before_phase = self.rc.phase().value
        self.rc.fold_rcm(rcm.ts, rcm.message, rcm.category.value, rcm.flag,
                         lap_number=rcm.lap_number)
        out = []
        flag_map = {
            "RED": ("RED_FLAG", "RED"), "CHEQUERED": ("SESSION_END", "CHEQUERED"),
        }
        if rcm.flag == "RED":
            ev = self.sig.race_control_event("RED_FLAG", f"RCM{rcm.rcm_key}",
                                             rcm.message, rcm.ts)
            if ev:
                out.append(ev)
        elif "SAFETY CAR DEPLOYED" in (rcm.message or "").upper():
            ev = self.sig.race_control_event("SAFETY_CAR", f"RCM{rcm.rcm_key}",
                                             rcm.message, rcm.ts)
            if ev:
                out.append(ev)
        elif "VSC DEPLOYED" in (rcm.message or "").upper():
            ev = self.sig.race_control_event("VSC", f"RCM{rcm.rcm_key}",
                                             rcm.message, rcm.ts)
            if ev:
                out.append(ev)

        after_phase = self.rc.phase().value
        if after_phase != before_phase:
            self._state_transition_count += 1
            ev = self.sig.session_state_changed(before_phase, after_phase,
                                                self._state_transition_count, rcm.ts)
            if ev:
                out.append(ev)
        return out

    def on_correction(self, corr, envelope):
        key = (corr.driver_number, corr.lap_number)
        self._corr_open[key] = corr.kind.value == "LAP_DELETED"
        return []

    def on_lap(self, lap, envelope):
        deleted = self._corr_open.get((lap.driver_number, lap.lap_number), False)
        stint_no = self.stints.current_stint.get(lap.driver_number)
        cl = ClassifiedLap(
            session_id=lap.session_id,
            driver_number=lap.driver_number,
            lap_number=lap.lap_number,
            started_at=lap.started_at,
            duration_s=lap.duration_s,
            sector_times_s=(lap.sector1_s, lap.sector2_s, lap.sector3_s),
            is_pit_out=lap.is_pit_out_lap or False,
            deleted=deleted,
        )
        classified = self.classifier.classify(cl)

        result = self.timing.fold_lap(
            driver_number=lap.driver_number, lap_number=lap.lap_number,
            duration_s=lap.duration_s, deleted=deleted)
        pb = bool(result and result.get("personal_best"))
        sb_change = bool(result and result.get("session_best"))  # excludes first
        events = self.sig.lap_completed(
            driver_number=lap.driver_number, lap_number=lap.lap_number,
            duration_s=lap.duration_s, personal_best=pb,
            session_best_change=sb_change, is_first_sb=False,
            ts=envelope.source_timestamp or _now())

        self.pace.fold_classified(classified)
        self.pace.attach_lap_object(classified)
        self.stints.note_lap(lap.driver_number, lap.lap_number, lap.duration_s)

        slope = self.pace.pace_trend(lap.driver_number)
        if slope is not None and self.ctx.is_meaningful("rolling_pace"):
            ev = self.sig.pace_shift(lap.driver_number, slope, lap.lap_number,
                                     envelope.source_timestamp or _now())
            if ev:
                events.append(ev)

        # ---- Phase 5 folds (cheap, incremental) ----
        d = self.timing.state.driver(lap.driver_number)
        ca = PaceEngine.classify_clean_air(d.interval_s, None,
                                           is_leader=(d.position == 1))
        ta = self.traffic_model.classify(
            gap_ahead_s=d.interval_s, gap_behind_s=None)
        self.racepace2.fold_lap(__import__(
            "app.analysis.racepace2", fromlist=["LapRecord"]).LapRecord(
            driver_number=lap.driver_number, lap_number=lap.lap_number,
            duration_s=lap.duration_s or 0, clean_air=ca.value,
            traffic=ta.state.value,
            stint_number=classified.stint_number,
            tyre_age=self.stints.tyre_age(lap.driver_number, lap.lap_number),
        ))
        if classified.is_representative and lap.duration_s:
            self.traffic_model.fold_lap(lap.driver_number, ta.state, lap.duration_s)

        # pace gain/loss on rolling-5 movement
        w5 = self.pace.rolling_pace(lap.driver_number, 5)
        prev5 = self._last_window5.get(lap.driver_number)
        gl = self.racepace2.pace_gain_loss(lap.driver_number, prev5, w5)
        self._last_window5[lap.driver_number] = w5
        if gl:
            ev = self.sig.custom(gl, f"{lap.driver_number}|BUCKET{lap.lap_number//3}",
                                 ts=envelope.source_timestamp or _now(),
                                 drivers=(lap.driver_number,),
                                 metrics={"rolling5": w5})
            if ev:
                events.append(ev)

        # qualifying/practice intel folding
        if self.ctx.profile is not None and str(self.ctx.profile) == "Profile.QUALIFYING":
            sector_bests = {k: v for k, v in
                            enumerate((self.sectors.drivers.get(lap.driver_number).best.values()
                                       if self.sectors.drivers.get(lap.driver_number) else []), 1)}
            qd = self.quali.fold_best(lap.driver_number, lap.duration_s or 0, sector_bests)
            boundary, _pos = self.quali.boundary_time(part_size=10,
                                                      total_drivers=len(self.quali.drivers))
            cutoff_ev = self.quali.observe_boundary(boundary)
            if cutoff_ev:
                cev = self.sig.custom(cutoff_ev, f"BUCKET{lap.lap_number//2}",
                                      ts=envelope.source_timestamp or _now(),
                                      severity=Severity.NOTABLE,
                                      metrics={"boundary_s": boundary})
                if cev:
                    events.append(cev)
        return events

    def on_sector(self, sec, envelope):
        deleted = self._corr_open.get((sec.driver_number, sec.lap_number), False)
        c = self.sectors.fold_sector(
            driver_number=sec.driver_number, lap_number=sec.lap_number,
            sector_index=sec.sector_index, time_s=sec.time_s, deleted=deleted)
        if c is None:
            return []
        return [self.sig.sector_classified(c, sec.driver_number, sec.lap_number,
                                           envelope.source_timestamp or _now())]

    def on_position(self, pos, envelope):
        delta = self.timing.fold_position(pos.driver_number, pos.ts, pos.position)
        if delta is None:
            return []
        ev = self.sig.position_changed(pos.driver_number,
                                       pos.position + delta, pos.position,
                                       self.timing.state.driver(pos.driver_number).lap_number,
                                       pos.ts)
        return [ev] if ev else []

    def on_interval(self, iv, envelope):
        d = self.timing.state.driver(iv.driver_number)
        gap_value = iv.gap_to_leader_s if iv.gap_to_leader_s is not None else iv.gap_raw
        TimingEngine.apply_interval_sample(d, gap_value, iv.interval_s, lap=None)

        neighbors = self.gaps.neighbors_by_position(
            {n: dd.position or 0 for n, dd in self.timing.state.drivers.items()})
        ahead_n, _behind = neighbors.get(iv.driver_number, (None, None))

        events = []
        if ahead_n is not None and iv.interval_s is not None:
            prev_state = self.battles.battles.get((ahead_n, iv.driver_number))
            b = self.battles.update(ahead_n, iv.driver_number, iv.interval_s,
                                    lap=None,
                                    either_pitted_or_out=(
                                        self.timing.state.driver(ahead_n).in_pit
                                        or self.timing.state.driver(ahead_n).retired
                                        or d.in_pit or d.retired))
            if prev_state is None or prev_state.state is not b.state:
                ev = self.sig.battle_escalated(b, b.state,
                                               iv.ts or envelope.source_timestamp or _now())
                if ev:
                    events.append(ev)

        self.gaps.fold_interval(
            iv.driver_number,
            iv.gap_to_leader_s if iv.gap_to_leader_s is not None else None,
            iv.interval_s, iv.gap_raw, None, lap=None, car_ahead=ahead_n)
        return events

    def on_stint(self, stint, envelope):
        prev_current = self.stints.current_stint.get(stint.driver_number)
        self.stints.fold_stint_record(stint)
        new_current = self.stints.current(stint.driver_number)
        if new_current and stint.stint_number > (prev_current or 0):
            fit = self.stints.fit_driver_current(stint.driver_number)
            # fit the JUST-CLOSED stint (previous one) when available
            closed = self.stints.stints.get(stint.driver_number, {}).get(prev_current) \
                if prev_current else None
            if closed:
                closed.fit_degradation()
        return []

    def on_pit_stop(self, pit, envelope):
        self.strategy.fold_pit_stop(pit.lane_duration_s)
        self.timing.mark_pit(pit.driver_number, True)
        ev = self.sig.pit_stop(pit.driver_number, pit.ts, pit.lane_duration_s)
        return [ev] if ev else []

    def on_weather(self, wx, envelope):
        raw = self.weather.fold(
            ts=wx.ts, air_temp=wx.air_temp_c, track_temp=wx.track_temp_c,
            humidity=wx.humidity_pct, pressure=wx.pressure_hpa,
            rainfall=wx.rainfall, wind_direction=wx.wind_direction_deg,
            wind_speed=wx.wind_speed_mps)
        return self.sig.weather_events(raw, wx.ts)

    def on_car_sample(self, sample, envelope):
        return []  # telemetry analytics arrive with the telemetry engine phase

    # ------------------------------------------------- phase 5 intelligence --

    def intelligence(self) -> dict:
        """Deterministic advanced-intelligence summary (computed on demand)."""
        deg_by_stint: dict[int, float] = {}
        for num in self.stints.stints:
            s = self.stints.fit_driver_current(num)
            if s and s.degradation_rate_s_per_lap is not None and \
                    s.stint_number is not None:
                cur = self.stints.current_stint.get(num)
                if cur == s.stint_number:
                    deg_by_stint[s.stint_number] = s.degradation_rate_s_per_lap

        pace_summary: dict[str, dict] = {}
        for num in sorted(self.timing.state.drivers):
            capace, ca_conf = self.racepace2.clean_air_pace(num)
            tadj, ta_conf = self.racepace2.tyre_adjusted_pace(
                num, {k: v for k, v in deg_by_stint.items()})
            pace_summary[str(num)] = {
                "clean_air_pace": capace, "clean_air_confidence": ca_conf.value,
                "traffic_adjusted_pace": tadj,
                "tyre_adjusted_pace": None,   # computed per stint below (honest)
                "stint_normalized": self.racepace2.stint_normalized(
                    num, deg_by_stint),
            }

        traffic_states = {}
        for num, d in self.timing.state.drivers.items():
            ta = self.traffic_model.classify(gap_ahead_s=d.interval_s,
                                             gap_behind_s=None)
            traffic_states[str(num)] = ta.state.value

        strategy_top: dict | None = None
        if is_race_like(self.ctx.profile):
            num0 = next(iter(sorted(self.timing.state.drivers)), None)
            if num0 is not None:
                fit = self.stints.fit_driver_current(num0)
                max_lap = max((d.lap_number or 0) for d
                              in self.timing.state.drivers.values()) if \
                    self.timing.state.drivers else None
                total_laps = self.rc.projection.lap_count or (
                    max_lap + 12 if max_lap else None)  # ASSUMPTION documented
                strategy_top = self.strategy2.candidates(
                    compound=(self.stints.compound(num0).value
                              if self.stints.compound(num0) else None),
                    tyre_age=self.stints.tyre_age(num0, max_lap),
                    degradation_rate=fit.degradation_rate_s_per_lap if fit else None,
                    base_pace=fit.base_pace_s if fit else None,
                    laps_remaining=(total_lap - max_lap) if
                    (total_lap := total_laps) and max_lap else None,
                    pit_loss_s=(self.strategy.pit_loss_estimate()[0]),
                    sc_active=self.rc.phase().value == "SAFETY_CAR",
                    vsc_active=self.rc.phase().value == "VSC")

        return {
            "calc_version": CALC_VERSION,
            "profile": self.ctx.profile.value if self.ctx.profile else None,
            "race_pace_2": {
                "driver_pace": self.racepace2.driver_pace(),
                "team_pace": self.racepace2.team_pace(),
                "field_pace": self.racepace2.field_pace(),
                "per_driver": pace_summary,
            },
            "tyres_2": {str(n): self.stints_summary_tyres2(n)
                        for n in sorted(self.stints.stints)},
            "traffic": traffic_states,
            "drs": {"supported": self.drs.supported},
            "battles_2": [
                b.as_dict() if hasattr(b, "as_dict") else b
                for b in [self.battles.active_battles()]
            ][0] if False else [
                {**{k: getattr(b, k) for k in
                    ("ahead", "behind", "state", "min_gap_s", "last_gap_s")},
                 "state": b.state.value}
                for b in self.battles.active_battles()
            ],
            "strategy_candidates": strategy_top,
            "qualifying": self.qualifying_intel() if
            (self.ctx.profile is not None and
             self.ctx.profile.value == "QUALIFYING") else None,
            "practice": self.practice_intel() if
            (self.ctx.profile is not None and
             self.ctx.profile.value == "PRACTICE") else None,
        }

    def stints_summary_tyres2(self, driver_number: int) -> list[dict]:
        from app.analysis.tyres2 import TyreIntelligence2

        t2 = TyreIntelligence2()
        self.stints.reassign_driver(driver_number)   # fresh assignment
        out = []
        dmap = self.stints._ledger.get(driver_number, {})
        for sn, stint in sorted(self.stints.stints.get(driver_number, {}).items()):
            if stint.lap_start is None:
                continue
            laps = [(ln - stint.lap_start, dur) for ln, dur in dmap.items()
                    if stint.lap_start <= ln and
                    (stint.lap_end is None or ln <= stint.lap_end)]
            r = t2.analyse(session_id=self.session_id,
                           driver_number=driver_number, stint_number=sn,
                           compound=stint.compound.value, laps=laps)
            d = r.as_dict()
            d["stint_number"] = sn
            out.append(d)
        return out

    def qualifying_intel(self) -> dict:
        drivers = []
        for n, d in sorted(self.quali.drivers.items()):
            drivers.append({
                "driver_number": n, "best_lap_s": d.best_lap_s,
                "attempts": d.attempts,
                **self.quali.elimination_risk(n),
                "theoretical_gain_s": self.quali.theoretical_gain(n),
            })
        proj, conf = self.quali.projected_cutoff()
        return {"phase": self.quali.phase, "drivers": drivers,
                "cutoff_projection": proj, "cutoff_confidence": conf.value,
                "evolution": self.quali.track_evolution()}

    def practice_intel(self) -> dict:
        summary = {}
        for n in sorted(self.practice.stints):
            per_stint = []
            for sn, laps in sorted(self.practice.stints[n].items()):
                comp = self.practice.compounds.get(n, {}).get(sn)
                runs = self.practice.fold_stint_laps(n, sn, laps, comp)
                per_stint.append({
                    "stint": sn, "compound": comp,
                    "runs": [vars(r) | {"kind": r.kind} for r in runs],
                })
            summary[str(n)] = {
                "long_run_average": self.practice.long_run_average(n),
                "short_run_average": self.practice.short_run_average(n),
                "consistency_cv": self.practice.consistency(n),
                "stints": per_stint,
            }
        return {"drivers": summary}

    # ------------------------------------------------------------- output ----

    def snapshot(self) -> SessionSnapshot:
        return self.builder.build([e.as_dict() for e in self.sig.events[-25:]])

    def snapshot_dict(self) -> dict:
        snap = self.snapshot()
        d = self.builder.to_dict(snap)
        d["calc_version"] = CALC_VERSION
        d["profile"] = self.ctx.profile.value if self.ctx.profile else None
        return d

    def degradation_summary(self) -> dict:
        out = {}
        for num in sorted(self.stints.stints):
            s = self.stints.fit_driver_current(num)
            if s and s.degradation_rate_s_per_lap is not None:
                out[num] = {
                    "estimated_degradation_s_per_lap": s.degradation_rate_s_per_lap,
                    "base_pace_s": s.base_pace_s,
                    "r_squared": s.r_squared,
                    "samples": s.n_samples,
                    "excluded": s.n_excluded,
                    "confidence": s.confidence.value,
                    "label": "ESTIMATED DEGRADATION",
                }
        return out


def _rebuild(model_type: str, info: dict):
    from app.core import models as M

    cls = getattr(M, model_type)
    payload = {k: v for k, v in info.items() if k != "type"}
    return cls.model_validate(payload)


def _now():
    return datetime.now(timezone.utc)


_HANDLERS = {
    "SessionInfo": AnalysisEngine.on_session,
    "Driver": AnalysisEngine.on_driver,
    "RaceControlEvent": AnalysisEngine.on_rcm,
    "LapCorrection": AnalysisEngine.on_correction,
    "Lap": AnalysisEngine.on_lap,
    "SectorTime": AnalysisEngine.on_sector,
    "PositionUpdate": AnalysisEngine.on_position,
    "TimingInterval": AnalysisEngine.on_interval,
    "TyreStint": AnalysisEngine.on_stint,
    "PitStop": AnalysisEngine.on_pit_stop,
    "WeatherPoint": AnalysisEngine.on_weather,
    "TelemetryCarSample": AnalysisEngine.on_car_sample,
}
