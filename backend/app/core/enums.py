"""Closed enumerations for the canonical domain.

Unknown upstream values MUST map to explicit *_UNKNOWN variants - never
silently coerced and never fabricated.
"""

from __future__ import annotations

from enum import Enum


class ProvenanceClass(str, Enum):
    """Where a value came from. Every persisted value carries exactly one."""

    A = "A"  # direct live observation
    B = "B"  # historical observation
    C = "C"  # deterministic derivation
    D = "D"  # statistical / model prediction
    E = "E"  # LLM interpretation
    F = "F"  # unavailable (never persisted as a value; used in capabilities)


class ProviderName(str, Enum):
    OPENF1 = "openf1"
    REPLAY = "replay"
    LIVETIMING = "livetiming"  # direct F1 SignalR feed (Phase 1.5 abstraction)
    FASTF1 = "fastf1"
    JOLPICA = "jolpica"
    F1DB = "f1db"


class SessionType(str, Enum):
    PRACTICE = "Practice"
    QUALIFYING = "Qualifying"
    SPRINT_QUALI = "Sprint Qualifying"  # OpenF1 uses "Sprint Qualifying"/"Sprint Shootout"
    SPRINT_SHOOTOUT = "Sprint Shootout"
    SPRINT = "Sprint"
    RACE = "Race"
    UNKNOWN = "UNKNOWN"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class Compound(str, Enum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    TEST_UNKNOWN = "TEST_UNKNOWN"  # upstream "UNKNOWN"/"TEST_UNKNOWN" compound
    UNKNOWN = "UNKNOWN"


class DriverStatus(str, Enum):
    """Phase 1 keeps this minimal; richer states arrive with the live feed."""

    ON_TRACK = "ON_TRACK"
    PIT = "PIT"
    OUT_LAP = "OUT_LAP"
    RETIRED = "RETIRED"
    UNKNOWN = "UNKNOWN"


class RCMCategory(str, Enum):
    FLAG = "Flag"
    OTHER = "Other"
    SAFETY_CAR = "Safety Car"
    DRS = "DRS"
    INVESTIGATION = "Investigation"
    PENALTY = "Penalty"
    INCLEMENT_WEATHER = "Inclement Weather"
    TRACK_PROBLEM = "Track Problem"
    TRACK_LIMITS = "Track Limits"  # not observed yet upstream; reserved
    SESSION = "Session"
    UNKNOWN = "UNKNOWN"


def enum_or_unknown(enum_cls: type[Enum], raw: object) -> Enum:
    """Map an arbitrary upstream string to the enum or its *_UNKNOWN variant."""
    if isinstance(raw, enum_cls):
        return raw
    if raw is None:
        return enum_cls["UNKNOWN"]
    text = str(raw).strip()
    for member in enum_cls:
        if member.value.lower() == text.lower():
            return member
    return enum_cls["UNKNOWN"]
