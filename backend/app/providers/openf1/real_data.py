"""Guards for acquiring real OpenF1 data used as validation evidence.

validate_rows_identity exists because of a failure actually observed in
this project: a tool-level HTTP cache answered requests for several
different drivers/sessions with the same real driver-55 / session-9159
car_data. Every row was genuine F1 telemetry - just not the telemetry
that was asked for. Nothing in the OpenF1 layer compared request against
response, so it would have been accepted as a real multi-driver pair.

select_reference_lap encodes the lap-selection rule for real A/B
comparisons explicitly, so the choice of lap is never implicit.
"""

from __future__ import annotations

from typing import Any

from app.providers.openf1.client import OpenF1Error


class IdentityMismatch(OpenF1Error):
    """A response contained rows for a driver/session that was not requested."""


def validate_rows_identity(
    rows: list[dict[str, Any]], *, driver_number: int | str, session_key: int | str,
) -> int:
    """Raise IdentityMismatch unless EVERY row carries exactly the requested
    driver_number and session_key. Returns the number of rows checked.

    One contaminating row fails the whole response - partially-wrong data
    is not filtered down to its "good" part, because a response that is
    wrong anywhere cannot be trusted anywhere. A row missing either field
    also fails: identity that can't be checked isn't verified.
    """
    want_driver, want_session = int(driver_number), int(session_key)
    for i, row in enumerate(rows):
        got_driver, got_session = row.get("driver_number"), row.get("session_key")
        if got_driver is None or got_session is None:
            raise IdentityMismatch(
                f"row {i} lacks driver_number/session_key - identity unverifiable")
        if int(got_driver) != want_driver:
            raise IdentityMismatch(
                f"row {i}: requested driver_number={want_driver}, got {got_driver}")
        if int(got_session) != want_session:
            raise IdentityMismatch(
                f"row {i}: requested session_key={want_session}, got {got_session}")
    return len(rows)


def _eligible(lap: dict[str, Any]) -> bool:
    return lap.get("lap_duration") is not None and not lap.get("is_pit_out_lap")


def select_reference_lap(
    laps: list[dict[str, Any]], lap_number: int | None = None,
) -> dict[str, Any] | None:
    """Pick the lap to use for one side of a real A/B comparison.

    Rule: an explicitly requested lap_number is honoured only if that lap
    is complete (lap_duration reported) and not a pit-out lap - otherwise
    ValueError, never a silent substitute. Without lap_number, the fastest
    complete non-pit-out lap is used (ties: lowest lap number). Returns
    None when no lap qualifies.

    This uses only fields OpenF1 itself reports; it does not infer pit-in
    laps, yellow flags or track limits (LapClassifier's job, and it needs
    race-control context this acquisition step doesn't have).
    """
    if lap_number is not None:
        for lap in laps:
            if int(lap.get("lap_number", -1)) == int(lap_number):
                if not _eligible(lap):
                    raise ValueError(
                        f"lap {lap_number} is incomplete or a pit-out lap - "
                        "not usable as a reference lap")
                return lap
        raise ValueError(f"lap {lap_number} not present in the provided laps")

    candidates = [lap for lap in laps if _eligible(lap)]
    if not candidates:
        return None
    return min(candidates, key=lambda lap: (lap["lap_duration"], lap["lap_number"]))
