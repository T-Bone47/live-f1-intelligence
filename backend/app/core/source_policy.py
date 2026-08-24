"""Source-priority matrix + multi-source reconciliation policy (Phase 1.5).

RECOMMENDED priority per data domain, based on Phase 1/1.5 VERIFICATION ONLY
(see docs/PROVIDER_COMPARISON.md). Configurable via config; never hard-coded
into providers.

Reconciliation principle: values are NEVER merged or averaged. The primary
source wins; the challenger's value is retained as alternate provenance; a
CONFLICT decision is surfaced to the quality system for human review.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.providers.base import Channel


class Resolution(str, Enum):
    PRIMARY = "PRIMARY"          # take primary source's value
    FRESHER = "FRESHER"          # timestamps disagree beyond window -> fresher wins
    CONFLICT = "CONFLICT"        # same fact, irreconcilable values -> flag it
    NO_CONTEST = "NO_CONTEST"    # only one source has the value


# Recommended matrix: provider names in priority order per channel.
# signalr = direct F1 feed; openf1 = OpenF1; fastf1 = FastF1 (historical);
# jolpica = Jolpica; replay never participates in live priority.
RECOMMENDED_PRIORITY: dict[str, tuple[str, ...]] = {
    Channel.LAP.value: ("signalr", "openf1", "fastf1"),
    Channel.CAR_DATA.value: ("signalr", "openf1", "fastf1"),
    Channel.LOCATION.value: ("signalr", "openf1", "fastf1"),
    Channel.INTERVALS.value: ("signalr", "openf1"),
    Channel.STINT.value: ("signalr", "openf1", "fastf1"),
    Channel.PIT.value: ("signalr", "openf1", "fastf1"),
    Channel.WEATHER.value: ("signalr", "openf1", "fastf1"),
    Channel.RACE_CONTROL.value: ("signalr", "openf1"),
    Channel.POSITION.value: ("signalr", "openf1"),
    Channel.RESULTS.value: ("jolpica",),
    Channel.STANDINGS.value: ("jolpica",),
    Channel.SCHEDULE.value: ("jolpica", "openf1"),
}


def primary_for(channel: str | Channel,
                priorities: dict[str, tuple[str, ...]] | None = None) -> str | None:
    matrix = priorities or RECOMMENDED_PRIORITY
    order = matrix.get(getattr(channel, "value", channel))
    return order[0] if order else None


@dataclass(frozen=True)
class ReconciliationDecision:
    resolution: Resolution
    winner_source: str | None
    loser_source: str | None = None
    reason: str = ""


class ReconciliationPolicy:
    """Decides between two sources reporting the 'same' canonical fact.

    Same-fact matching is by canonical identity keys (session/driver/lap/ts).
    Timestamp tolerance bounds what counts as 'same instant'; outside it the
    fresher observation wins because the underlying reality moved on.
    """

    def __init__(self, primary_source: str, freshness_window_s: float = 2.0) -> None:
        self.primary = primary_source
        self.window = freshness_window_s

    def resolve(
        self,
        *,
        primary_value: object | None,
        secondary_value: object | None,
        primary_ts: float | None,
        secondary_ts: float | None,
        primary_source: str | None = None,
        secondary_source: str | None = None,
    ) -> ReconciliationDecision:
        if secondary_value is None:
            return ReconciliationDecision(Resolution.NO_CONTEST, self.primary)
        if primary_value is None:
            src = secondary_source or "secondary"
            return ReconciliationDecision(Resolution.FRESHER, src,
                                          reason="primary missing value")
        if primary_value == secondary_value:
            return ReconciliationDecision(Resolution.PRIMARY, self.primary,
                                          reason="values agree")
        if primary_ts is not None and secondary_ts is not None and \
                abs(primary_ts - secondary_ts) > self.window:
            newer_is_primary = primary_ts >= secondary_ts
            return ReconciliationDecision(
                Resolution.FRESHER,
                self.primary if newer_is_primary else (secondary_source or "secondary"),
                loser_source=None if newer_is_primary else self.primary,
                reason="observations outside freshness window",
            )
        return ReconciliationDecision(
            Resolution.CONFLICT, self.primary,
            loser_source=secondary_source,
            reason="same-fact disagreement within window - flagged, primary kept, "
                   "alternate retained with provenance",
        )
