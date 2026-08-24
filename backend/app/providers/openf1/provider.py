"""OpenF1 provider.

Two modes:
- "historical": backfill a completed session (class B provenance). Ends when
  every channel cursor is exhausted.
- "live": poll an in-progress session on an interval (class A provenance).
  NOTE (verified): live-session access requires an OpenF1 sponsor token;
  without it the API restricts access during the session window. The provider
  surfaces that condition honestly rather than pretending to be live.

The provider yields RawItems; normalization happens downstream.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from app.config import Settings
from app.core.enums import ProvenanceClass
from app.core.models import SessionInfo
from app.providers.base import Capabilities, Channel, RawItem
from app.providers.openf1.client import OpenF1Client, OpenF1Error, RateLimited
from app.providers.openf1.mapping import parse_ts, safe, to_session

log = logging.getLogger(__name__)

LIVE_WINDOW_BEFORE = timedelta(minutes=45)
LIVE_WINDOW_AFTER = timedelta(minutes=30)
# Historical backfill sweeps bounded windows so a whole race's telemetry is
# never fetched in one response.
HIST_WINDOW = timedelta(minutes=10)


class OpenF1Provider:
    name = "openf1"

    def __init__(self, client: OpenF1Client, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self._mode: str = "historical"

    def capabilities(self) -> Capabilities:
        return Capabilities(
            session_discovery=True,
            live=True,
            historical=True,
            timing_intervals=True,
            laps=True,
            sectors=True,
            mini_segments=True,
            telemetry_car=True,
            telemetry_location=True,
            stints=True,
            pits=True,
            weather=True,
            race_control=True,
            lap_corrections=True,
            positions=True,
            team_radio=False,  # endpoint exists upstream; out of Phase 1 scope
            verified=(
                "full-race backfill 2026 Dutch GP: 1,067,193 events, 0 malformed",
                "laps filter via date_start> (date> silently returns empty)",
                "intervals gap mixed-type ('+1 LAP') preserved verbatim",
                "rcm marshal-sector numbers up to 18+ observed",
                "empty results arrive as HTTP 200 OR 404 with same body",
            ),
            assumed=(),
            notes=(
                "REST polling, not push streaming",
                "year= filter verified broken upstream - use meeting/session keys",
                "live-window access requires sponsor token (free tier is historical)",
                "car_data drs field nullable",
                "rate limits empirically stricter than documented - client "
                "defaults 1.8 rps / 20 rpm",
            ),
        )

    # ------------------------------------------------------- discovery ------

    async def discover_sessions(self, year: int | None = None) -> list[SessionInfo]:
        """List recent sessions. `year` filter upstream is unreliable; when it
        returns nothing we fall back to paging meetings by key descending."""
        sessions: list[SessionInfo] = []
        if year is not None:
            rows = await self._client.meetings(year=year)
        else:
            rows = await self._recent_meetings_scan()
        for m in rows[:40]:
            try:
                mk = int(m["meeting_key"])
            except (KeyError, TypeError, ValueError):
                continue
            for srow in await self._client.sessions_for_meeting(mk):
                try:
                    sessions.append(safe(to_session, srow))
                except Exception as exc:  # noqa: BLE001
                    log.warning("skipping malformed session row: %s", exc)
        return sessions

    async def _recent_meetings_scan(self) -> list[dict]:
        """Meetings endpoint has no reliable date filter; scan recent keys."""
        found: list[dict] = []
        probe = 2000
        empty_streak = 0
        while probe > 1200 and len(found) < 60 and empty_streak < 30:
            rows = await self._client.meetings(meeting_key=probe)
            if rows:
                found.extend(rows)
                empty_streak = 0
            else:
                empty_streak += 1
            probe -= 1
        found.sort(key=lambda r: str(r.get("date_start", "")), reverse=True)
        return found

    async def resolve_session(self, session_ref: str) -> SessionInfo:
        """Accept 'latest', a raw session_key, or canonical '<provider>:<key>'."""
        ref = session_ref.strip()
        if ref.lower() == "latest":
            rows = await self._client.sessions_latest()
            if not rows:
                raise OpenF1Error("no latest session found")
            return safe(to_session, rows[0])
        raw_key = ref.split(":", 1)[1] if ":" in ref else ref
        rows = await self._client.get("sessions", {"session_key": raw_key})
        if not rows:
            raise OpenF1Error(f"session {ref} not found")
        return safe(to_session, rows[0])

    @staticmethod
    def classify_session_state(session: SessionInfo) -> str:
        now = datetime.now(tz=timezone.utc)
        if session.date_start and session.date_end:
            if session.date_start - LIVE_WINDOW_BEFORE <= now <= session.date_end + LIVE_WINDOW_AFTER:
                return "live"
            if now > session.date_end + LIVE_WINDOW_AFTER:
                return "historical"
            return "scheduled"
        return "unknown"

    # ------------------------------------------------------------- run ------

    async def run(self, session: SessionInfo) -> AsyncIterator[RawItem]:
        state = self.classify_session_state(session)
        self._mode = "live" if state == "live" else "historical"
        cls = ProvenanceClass.A if self._mode == "live" else ProvenanceClass.B
        log.info(
            "OpenF1 run mode=%s state=%s session=%s", self._mode, state, session.provider_session_key
        )
        if state == "scheduled":
            log.info("session %s not started yet - nothing to ingest", session.provider_session_key)
            return

        yield RawItem(
            channel=Channel.SESSION_META,
            payload=self._session_payload(session),
            source_timestamp=session.provenance.source_timestamp,
            provenance_class=cls,
        )

        sk = session.provider_session_key
        # Seed cursors near the session start (NOT epoch): windowed sweeps must
        # begin where the data begins or they waste the entire rate-limit
        # budget walking decades of empty windows.
        seed = (session.date_start - LIVE_WINDOW_BEFORE) if session.date_start else (
            datetime.now(tz=timezone.utc) - timedelta(hours=6)
        )
        cursors = _Cursors(seed=seed)

        drivers_rows = await self._client.drivers(sk)
        for row in drivers_rows:
            yield RawItem(
                channel=Channel.DRIVER_LIST,
                payload=row,
                source_timestamp=None,
                provenance_class=cls,
            )

        live = self._mode == "live"
        session_end = session.date_end
        rounds = 0

        while True:
            batch: list[RawItem] = []
            batch += await self._poll_laps(sk, cursors, cls, session_end, live)
            batch += await self._poll_generic(
                sk, cursors, cls, session_end, live,
                include_stints=(live or bool(batch) or rounds % 10 == 0),
            )
            for item in batch:
                yield item
            cursors.note_round(bool(batch))
            rounds += 1
            if not live:
                # Terminated when every windowed cursor has swept past the end
                # of the session (+ margin), or a hard safety cap is reached.
                threshold = (session_end + LIVE_WINDOW_AFTER) if session_end else None
                if (threshold and cursors.past(threshold)) or cursors.rounds > 600:
                    if cursors.rounds > 600 and not (threshold and cursors.past(threshold)):
                        log.warning("historical backfill hit round cap; some data may be missing")
                    break
                await asyncio.sleep(1.0)  # pacing; token bucket adds more as needed
            else:
                await asyncio.sleep(self._settings.poll_interval_seconds)

    def _session_payload(self, session: SessionInfo) -> dict:
        return {
            "session_key": session.provider_session_key,
            "meeting_key": session.provider_meeting_key,
            "session_type": session.session_type.value,
            "session_name": session.session_name,
            "date_start": session.date_start.isoformat() if session.date_start else None,
            "date_end": session.date_end.isoformat() if session.date_end else None,
            "circuit_short_name": session.circuit_short_name,
            "country_code": session.country_code,
            "country_name": session.country_name,
            "location": session.location,
            "gmt_offset": session.gmt_offset,
            "year": session.year,
            "is_cancelled": session.is_cancelled,
            "meeting_name": None,
        }

    async def _poll_laps(self, sk: str, cursors: "_Cursors", cls: ProvenanceClass,
                         session_end: datetime | None, live: bool) -> list[RawItem]:
        cursor = cursors.get("laps")
        # laps are low-volume: single ranged call per sweep
        until = None if live else (
            (session_end + LIVE_WINDOW_AFTER) if session_end else cursor + HIST_WINDOW
        )
        rows = await self._client.laps_since(
            sk, cursor.isoformat(), until.isoformat() if until else None
        )
        items: list[RawItem] = []
        for row in sorted(rows, key=_sort_by_date_start):
            ts_raw = row.get("date_start")
            if ts_raw:
                items.append(RawItem(Channel.LAP, row, parse_ts(ts_raw), cls))
        if items:
            cursors.set(
                "laps",
                max(i.source_timestamp for i in items if i.source_timestamp) + timedelta(microseconds=1),
            )
        elif until:
            cursors.set("laps", until)  # empty window: skip ahead
        return items

    @staticmethod
    def _window_end(cursor: datetime, session_end: datetime | None, live: bool) -> datetime | None:
        if live:
            return None
        cap = (session_end + LIVE_WINDOW_AFTER) if session_end else (cursor + HIST_WINDOW)
        return min(cursor + HIST_WINDOW, cap)

    async def _poll_generic(self, sk: str, cursors: "_Cursors", cls: ProvenanceClass,
                            session_end: datetime | None, live: bool,
                            include_stints: bool = True) -> list[RawItem]:
        items: list[RawItem] = []

        async def collect(channel: Channel, fetch, cursor_attr: str, ts_field: str,
                          until_override: datetime | None = None) -> None:
            cursor: datetime = cursors.get(cursor_attr)
            if not live and until_override is not None:
                # low-volume channel: one ranged call covering the whole session
                until = until_override
            else:
                until = self._window_end(cursor, session_end, live)
            try:
                rows = await fetch(cursor.isoformat(), until.isoformat() if until else None)
            except RateLimited as exc:
                log.warning("%s rate limited: %s", channel.value, exc)
                return
            new_items: list[RawItem] = []
            max_ts: datetime | None = None
            for row in rows:
                raw_ts = row.get(ts_field)
                item_ts = parse_ts(raw_ts) if raw_ts else None
                # include only records at/after the cursor to avoid re-emitting
                if item_ts is None or item_ts >= cursor:
                    new_items.append(RawItem(channel, row, item_ts, cls))
                    if item_ts and (max_ts is None or item_ts > max_ts):
                        max_ts = item_ts
            if max_ts:
                cursors.set(cursor_attr, max_ts + timedelta(microseconds=1))
            elif until:
                cursors.set(cursor_attr, until)  # empty window: skip ahead
            items.extend(new_items)

        skc = sk  # local alias for closures below
        # Low-volume channels make ONE ranged call over the whole session;
        # only high-rate telemetry channels use bounded windows.
        full_until = (session_end + LIVE_WINDOW_AFTER) if session_end else None
        await collect(
            Channel.CAR_DATA,
            lambda c, u: self._client.car_data_since(skc, c, u),
            "car_data",
            "date",
        )
        await collect(
            Channel.LOCATION,
            lambda c, u: self._client.location_since(skc, c, u),
            "location",
            "date",
        )
        await collect(
            Channel.PIT,
            lambda c, u: self._client.pits_since(skc, c, u),
            "pit",
            "date",
            until_override=full_until,
        )
        await collect(
            Channel.WEATHER,
            lambda c, u: self._client.weather_since(skc, c, u),
            "weather",
            "date",
            until_override=full_until,
        )
        await collect(
            Channel.RACE_CONTROL,
            lambda c, u: self._client.race_control_since(skc, c, u),
            "race_control",
            "date",
            until_override=full_until,
        )
        await collect(
            Channel.POSITION,
            lambda c, u: self._client.positions_since(skc, c, u),
            "position",
            "date",
            until_override=full_until,
        )
        await collect(
            Channel.INTERVALS,
            lambda c, u: self._client.intervals_since(skc, c, u),
            "intervals",
            "date",
            until_override=full_until,
        )

        # stints carry no timestamps upstream; refresh only when needed to
        # conserve rate-limit quota (they dedupe downstream anyway)
        if include_stints:
            try:
                for row in await self._client.stints(sk):
                    items.append(RawItem(Channel.STINT, row, None, cls))
            except RateLimited as exc:
                log.warning("stints rate limited: %s", exc)

        return items


def _sort_by_date_start(row: dict) -> str:
    return str(row.get("date_start", ""))


class _Cursors:
    """Per-channel `date>` cursors for incremental fetching."""

    FIELDS = (
        "laps", "car_data", "location", "pit", "weather",
        "race_control", "position", "intervals",
    )

    def __init__(self, seed: datetime) -> None:
        for name in self.FIELDS:
            setattr(self, name, seed)
        self.idle_rounds = 0
        self.rounds = 0

    def get(self, name: str) -> datetime:
        return getattr(self, name)

    def set(self, name: str, value: datetime) -> None:
        setattr(self, name, value)

    def past(self, threshold: datetime) -> bool:
        return all(self.get(name) >= threshold for name in self.FIELDS)

    def note_round(self, yielded: bool) -> None:
        self.rounds += 1
        self.idle_rounds = self.idle_rounds + 1 if not yielded else 0
