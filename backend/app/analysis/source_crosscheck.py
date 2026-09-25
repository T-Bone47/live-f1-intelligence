"""Two-source cross-check for reference data (results, qualifying, standings).

Policy (app.core.source_policy): values are NEVER merged or averaged. The
primary keeps its value; every disagreement is surfaced as a Discrepancy:
- CONFLICT:   both sources state the fact and the values differ;
- NO_CONTEST: only one source states it (missing row or field).

Identity is never guessed: session results match on the car number raced in
that session; standings match on the normalized family name. A duplicate
key on either side raises AmbiguousIdentityError.

Times are compared as seconds, not strings: vendors format the same gap as
"+1:05.918" (Jolpica) and "+65.918s" (Blacktop). Parsed values are compared
exactly at the millisecond resolution both vendors publish - no tolerance.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.core.models import QualifyingResult, RaceResult, StandingsEntry
from app.core.source_policy import Resolution


class AmbiguousIdentityError(ValueError):
    pass


@dataclass(frozen=True)
class Discrepancy:
    subject: str
    field: str
    resolution: Resolution
    primary_value: Any
    challenger_value: Any


@dataclass
class CrosscheckReport:
    kind: str
    compared: int = 0
    discrepancies: list[Discrepancy] = field(default_factory=list)

    @property
    def conflicts(self) -> list[Discrepancy]:
        return [d for d in self.discrepancies if d.resolution is Resolution.CONFLICT]


def name_key(family_name: str | None) -> str:
    """Case/accent/space-insensitive key: 'Hülkenberg' == 'Hulkenberg'."""
    # NFKD splits 'ü' into 'u' + a combining mark; the [^a-z] filter drops it.
    text = unicodedata.normalize("NFKD", family_name or "")
    return re.sub(r"[^a-z]", "", text.casefold())


_TIME = re.compile(r"^\+?(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)s?$")


def time_to_seconds(raw: str | None) -> float | None:
    """'1:46:37.418' | '1:30.984' | '+0.812' | '+65.918s' | '+1:05.918' -> s."""
    if not raw:
        return None
    m = _TIME.match(raw.strip())
    if not m:
        return None
    a, b, secs = m.groups()
    if b is not None:  # h:mm:ss.fff
        return int(a) * 3600 + int(b) * 60 + float(secs)
    if a is not None:  # m:ss.fff
        return int(a) * 60 + float(secs)
    return float(secs)


def _ms(raw: str | None) -> int | None:
    s = time_to_seconds(raw)
    return round(s * 1000) if s is not None else None


def _index(rows: Iterable[Any], key: Callable[[Any], str | None], side: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in rows:
        k = key(row)
        if not k:
            raise AmbiguousIdentityError(f"{side}: row without identity key: {row!r}")
        if k in out:
            raise AmbiguousIdentityError(f"{side}: duplicate identity {k!r}")
        out[k] = row
    return out


def _compare(kind: str, primary: dict[str, Any], challenger: dict[str, Any],
             fields: dict[str, Callable[[Any], Any]]) -> CrosscheckReport:
    rep = CrosscheckReport(kind=kind)
    for subject in sorted(set(primary) | set(challenger)):
        p, c = primary.get(subject), challenger.get(subject)
        if p is None or c is None:
            rep.discrepancies.append(Discrepancy(
                subject, "row", Resolution.NO_CONTEST,
                "present" if p is not None else None,
                "present" if c is not None else None))
            continue
        rep.compared += 1
        for name, get in fields.items():
            pv, cv = get(p), get(c)
            if pv is None and cv is None:
                continue
            if pv is None or cv is None:
                rep.discrepancies.append(Discrepancy(subject, name, Resolution.NO_CONTEST, pv, cv))
            elif pv != cv:
                rep.discrepancies.append(Discrepancy(subject, name, Resolution.CONFLICT, pv, cv))
    return rep


def _car(row: RaceResult | QualifyingResult) -> str | None:
    return f"#{row.driver_number}" if row.driver_number is not None else None


def crosscheck_race(primary: list[RaceResult], challenger: list[RaceResult]) -> CrosscheckReport:
    return _compare("race", _index(primary, _car, "primary"),
                    _index(challenger, _car, "challenger"), {
        "position": lambda r: r.position,
        "points": lambda r: r.points,
        "laps_completed": lambda r: r.laps_completed,
        "finish_time_ms": lambda r: _ms(r.finish_time_raw),
        "best_lap_ms": lambda r: _ms(r.fastest_lap_raw),
    })


def crosscheck_quali(primary: list[QualifyingResult],
                     challenger: list[QualifyingResult]) -> CrosscheckReport:
    return _compare("quali", _index(primary, _car, "primary"),
                    _index(challenger, _car, "challenger"), {
        "position": lambda r: r.position,
        "q1": lambda r: _ms(r.q1_raw),
        "q2": lambda r: _ms(r.q2_raw),
        "q3": lambda r: _ms(r.q3_raw),
    })


def crosscheck_standings(primary: list[StandingsEntry],
                         challenger: list[StandingsEntry]) -> CrosscheckReport:
    def key(r: StandingsEntry) -> str | None:
        return name_key(r.family_name) or None

    return _compare("standings", _index(primary, key, "primary"),
                    _index(challenger, key, "challenger"), {
        "position": lambda r: r.position,
        "points": lambda r: r.points,
    })
