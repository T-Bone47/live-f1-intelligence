"""Session context (Phase 2): which calculations are meaningful per session.

Canonical types (from OpenF1 verified values):
  Practice | Qualifying | Sprint Qualifying | Sprint Shootout | Sprint | Race
Profile groups: PRACTICE | QUALIFYING | SPRINT | RACE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.enums import SessionType


class Profile(str, Enum):
    PRACTICE = "PRACTICE"
    QUALIFYING = "QUALIFYING"
    SPRINT = "SPRINT"
    RACE = "RACE"


_TYPE_TO_PROFILE = {
    SessionType.PRACTICE: Profile.PRACTICE,
    SessionType.QUALIFYING: Profile.QUALIFYING,
    SessionType.SPRINT_QUALI: Profile.QUALIFYING,
    SessionType.SPRINT_SHOOTOUT: Profile.QUALIFYING,
    SessionType.SPRINT: Profile.SPRINT,
    SessionType.RACE: Profile.RACE,
}

# metric -> profiles where it is meaningful
MEANINGFUL = {
    "rolling_pace": {Profile.PRACTICE, Profile.SPRINT, Profile.RACE},
    "stint_analysis": {Profile.PRACTICE, Profile.SPRINT, Profile.RACE},
    "degradation": {Profile.SPRINT, Profile.RACE},
    "pit_windows": {Profile.SPRINT, Profile.RACE},
    "undercut_overcut": {Profile.SPRINT, Profile.RACE},
    "battles": {Profile.QUALIFYING, Profile.SPRINT, Profile.RACE},
    "theoretical_lap": {Profile.PRACTICE, Profile.QUALIFYING},
    "elimination_projection": set(),          # Phase 3+ (needs part tracking)
    "clean_air": {Profile.SPRINT, Profile.RACE},
}


@dataclass
class SessionContext:
    session_id: str
    session_type: SessionType = SessionType.UNKNOWN

    @property
    def profile(self) -> Profile | None:
        return _TYPE_TO_PROFILE.get(self.session_type)

    def is_meaningful(self, metric: str) -> bool:
        prof = self.profile
        if prof is None:
            return False
        return prof in MEANINGFUL.get(metric, set())

    def meaningful_metrics(self) -> list[str]:
        return sorted(m for m in MEANINGFUL if self.is_meaningful(m))
