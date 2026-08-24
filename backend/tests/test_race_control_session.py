"""Race-control + session context tests (Phase 2)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.race_control import RaceControlState
from app.analysis.session import Profile, SessionContext
from app.core.enums import SessionType
from app.core.enums import SessionStatus


def ts(minute: float) -> datetime:
    return datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc).__class__.fromtimestamp(
        datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc).timestamp() + minute * 60,
        tz=timezone.utc,
    )


class TestFlagTimeline:
    def test_yellow_open_close(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(1), "YELLOW IN TRACK SECTOR 4", "Flag", "YELLOW", lap_number=3)
        assert rc.flags_during(ts(1.5), ts(2)) == {"YELLOW"}
        rc.fold_rcm(ts(2.5), "CLEAR IN TRACK SECTOR 4", "Flag", "CLEAR", lap_number=4)
        assert rc.flags_during(ts(3), ts(4)) == set()
        assert len(rc.periods) == 1 and rc.periods[0].end is not None

    def test_double_yellow_supersedes_yellow(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(1), "YELLOW S7", "Flag", "YELLOW", lap_number=5)
        rc.fold_rcm(ts(2), "DOUBLE YELLOW S7", "Flag", "DOUBLE YELLOW", lap_number=5)
        kinds = {p.kind for p in (rc.periods + list(rc._open.values()))}
        assert kinds == {"YELLOW", "DOUBLE_YELLOW"}

    def test_sc_period_lifecycle(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(10), "SAFETY CAR DEPLOYED", "SafetyCar", None, lap_number=12)
        assert rc.phase().value == "SAFETY_CAR"
        rc.fold_rcm(ts(20), "SAFETY CAR IN THIS LAP", "SafetyCar", None, lap_number=18)
        assert rc.phase().value == "LIVE"
        sc = [p for p in rc.periods if p.kind == "SAFETY_CAR"]
        assert sc and sc[0].start_lap == 12 and sc[0].end_lap == 18

    def test_vsc_lifecycle(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(5), "VSC DEPLOYED", "Other", None, lap_number=7)
        assert rc.phase().value == "VSC"
        rc.fold_rcm(ts(9), "VSC ENDING", "Other", None, lap_number=9)
        assert rc.phase().value == "LIVE"

    def test_red_flag_closes_everything(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(3), "YELLOW S2", "Flag", "YELLOW", lap_number=2)
        rc.fold_rcm(ts(4), "RED FLAG", "Flag", "RED", lap_number=3)
        assert rc.phase().value == "RED_FLAG"
        assert rc._open.keys() == {"RED_FLAG"}
        yellow = [p for p in rc.periods if p.kind == "YELLOW"]
        assert yellow and yellow[0].end is not None

    def test_chequered_closes_all(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(30), "SAFETY CAR DEPLOYED", "SafetyCar", None)
        rc.fold_rcm(ts(40), "CHEQUERED FLAG", "Flag", "CHEQUERED")
        assert not rc._open

    def test_timestamp_ordering_enforced(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(5), "CLEAR S2", "Flag", "CLEAR")     # out of order input
        rc.fold_rcm(ts(1), "YELLOW S2", "Flag", "YELLOW")
        # last_update tracks max seen; no crash; deterministic state
        assert rc.last_update == ts(5)

    def test_flags_during_window_overlap_semantics(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(1.0), "YELLOW S1", "Flag", "YELLOW", lap_number=1)
        rc.fold_rcm(ts(2.0), "CLEAR S1", "Flag", "CLEAR", lap_number=2)
        inside = rc.flags_during(ts(1.2), ts(1.8))
        outside = rc.flags_during(ts(2.5), ts(3.0))
        assert inside == {"YELLOW"} and outside == set()


class TestPhaseFromMessages:
    def test_green_light_starts_live_from_unknown(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(0), "GREEN LIGHT - PIT EXIT OPEN", "Flag", "GREEN")
        assert rc.phase().value == "LIVE"

    def test_unknown_message_no_mutation(self):
        rc = RaceControlState()
        rc.fold_rcm(ts(0), "AWNINGS MAY BE USED", "Other", None)
        assert rc.phase().value == "UNKNOWN"


class TestSessionContext:
    def test_type_to_profile(self):
        assert SessionContext("s", SessionType.RACE).profile is Profile.RACE
        assert SessionContext("s", SessionType.SPRINT_QUALI).profile is Profile.QUALIFYING
        assert SessionContext("s", SessionType.PRACTICE).profile is Profile.PRACTICE

    def test_meaningfulness_matrix(self):
        race = SessionContext("s", SessionType.RACE)
        assert race.is_meaningful("degradation") is True
        assert race.is_meaningful("pit_windows") is True
        assert race.is_meaningful("theoretical_lap") is False
        quali = SessionContext("s", SessionType.QUALIFYING)
        assert quali.is_meaningful("theoretical_lap") is True
        assert quali.is_meaningful("pit_windows") is False

    def test_unknown_type_degrades_honestly(self):
        ctx = SessionContext("s", SessionType.UNKNOWN)
        assert ctx.profile is None
        assert ctx.is_meaningful("battles") is False

    def test_session_status_import_stable(self):
        assert SessionStatus.FINISHED.value == "FINISHED"
