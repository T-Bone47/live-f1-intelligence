"""Lap deletion / reinstatement detection from RaceControl messages.

VERIFIED real upstream patterns (2026 Dutch GP, session 11353):
  "CAR 27 (HUL) TIME 1:23.646 DELETED - TRACK LIMITS AT TURN 3 LAP 5"
  (driver_number FIELD is null upstream; the number lives in the text)
Reinstatement wording is expected as '... REINSTATED - ...' but has NOT yet
been observed in captured data -> marked ASSUMED, matched conservatively.

Corrections never overwrite history silently: a LapCorrection record is
emitted alongside the tombstone flag application.
"""

from __future__ import annotations

import re

from app.core.enums import ProvenanceClass
from app.core.models import CorrectionKind, LapCorrection

_DELETED_RE = re.compile(
    r"CAR\s+(?P<num>\d+)\s+\((?P<tla>[A-Z]{3})\)\s+TIME\s+"
    r"(?P<time>[\d:.]+)\s+DELETED\s+-\s+(?P<reason>.+?)\s+LAP\s+(?P<lap>\d+)",
    re.I,
)
_REINSTATED_RE = re.compile(
    r"CAR\s+(?P<num>\d+)\s+\((?P<tla>[A-Z]{3})\)\s+TIME\s+"
    r"(?P<time>[\d:.]+)\s+REINSTATED\s+-?\s*(?P<reason>.*?)\s*(?:LAP\s+(?P<lap>\d+))?$",
    re.I,
)
_TURN_RE = re.compile(r"TURN\s+(\d+)", re.I)


def parse_correction(message: str) -> tuple[CorrectionKind, dict] | None:
    """Return (kind, fields) for a recognized correction message, else None."""
    m = _DELETED_RE.search(message or "")
    if m:
        turn = _TURN_RE.search(m.group("reason"))
        return CorrectionKind.LAP_DELETED, {
            "driver_number": int(m.group("num")),
            "lap_number": int(m.group("lap")),
            "reason": m.group("reason").strip(),
            "deleted_time_raw": m.group("time"),
            "turn": int(turn.group(1)) if turn else None,
        }
    m = _REINSTATED_RE.search(message or "")
    if m:
        lap = m.group("lap")
        return CorrectionKind.LAP_REINSTATED, {
            "driver_number": int(m.group("num")),
            "lap_number": int(lap) if lap else None,
            "reason": (m.group("reason") or "").strip() or None,
            "deleted_time_raw": m.group("time"),
            "turn": None,
        }
    return None


def build_correction(message: str, session_id: str, rcm_key: str | None,
                     ts, provenance_class: ProvenanceClass = ProvenanceClass.A,
                     ) -> LapCorrection | None:
    """Build a canonical LapCorrection from an RCM message (or None)."""
    parsed = parse_correction(message)
    if parsed is None:
        return None
    kind, fields = parsed
    if fields["lap_number"] is None:
        return None  # cannot attribute without a lap - refuse to guess
    return LapCorrection(
        session_id=session_id,
        driver_number=fields["driver_number"],
        lap_number=fields["lap_number"],
        kind=kind,
        reason=fields["reason"],
        deleted_time_raw=fields["deleted_time_raw"],
        turn=fields["turn"],
        rcm_key=rcm_key,
        provenance={
            "provider": "openf1",
            "source_timestamp": ts,
            "provenance_class": provenance_class.value
            if hasattr(provenance_class, "value") else str(provenance_class),
        },
    )
