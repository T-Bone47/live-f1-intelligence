"""Database access: asyncpg pool + tiny SQL migration runner."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def connect(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=5)


async def apply_migrations(pool: asyncpg.Pool) -> list[str]:
    """Apply pending migrations in filename order. Optional/guarded migrations
    that fail are recorded as skipped with their error."""
    applied: list[str] = []

    await pool.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               name TEXT PRIMARY KEY,
               applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               status TEXT NOT NULL DEFAULT 'applied',
               detail TEXT
           )"""
    )
    rows = await pool.fetch("SELECT name FROM schema_migrations WHERE status = 'applied'")
    done = {r["name"] for r in rows}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations(name) VALUES($1)", path.name
                    )
            applied.append(path.name)
            log.info("migration applied: %s", path.name)
        except Exception as exc:  # noqa: BLE001
            log.warning("migration %s failed/skipped: %s", path.name, exc)
            await pool.execute(
                """INSERT INTO schema_migrations(name, status, detail)
                   VALUES($1, 'skipped', $2)
                   ON CONFLICT (name) DO UPDATE SET status='skipped', detail=$2""",
                path.name,
                str(exc)[:500],
            )
    return applied


# ---------------------------------------------------------------- helpers ---


def _ts(value: Any) -> Any:
    from datetime import datetime

    if isinstance(value, datetime):
        return value  # asyncpg wants tz-aware datetimes; ours are UTC-aware
    return value


class Repository:
    """Idempotent persistence of canonical models + envelopes."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def upsert_session(self, s) -> None:  # noqa: ANN001 SessionInfo
        await self.pool.execute(
            """
            INSERT INTO sessions(session_id, provider, provider_session_key,
                provider_meeting_key, year, session_type, session_name,
                circuit_short_name, country_code, country_name, location,
                gmt_offset, date_start, date_end, is_cancelled, status,
                provenance_class, source_timestamp, ingestion_timestamp)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
            ON CONFLICT (session_id) DO UPDATE SET
                status = EXCLUDED.status,
                is_cancelled = EXCLUDED.is_cancelled,
                ingestion_timestamp = now()
            """,
            s.session_id, s.provider.value, s.provider_session_key,
            s.provider_meeting_key, s.year, s.session_type.value, s.session_name,
            s.circuit_short_name, s.country_code, s.country_name, s.location,
            s.gmt_offset, _ts(s.date_start), _ts(s.date_end), s.is_cancelled,
            s.status.value, s.provenance.provenance_class.value,
            _ts(s.provenance.source_timestamp),
            _ts(s.provenance.ingestion_timestamp),
        )

    async def upsert_team(self, t) -> None:  # noqa: ANN001 Team
        await self.pool.execute(
            """
            INSERT INTO teams(team_id, display_name, colour_hex, provenance_class)
            VALUES($1,$2,$3,$4)
            ON CONFLICT (team_id) DO NOTHING
            """,
            t.team_id, t.display_name, t.colour_hex, t.provenance.provenance_class.value,
        )

    async def upsert_driver(self, d, session_id: str | None = None,
                            driver_number: int | None = None) -> None:  # noqa: ANN001 Driver
        await self.pool.execute(
            """
            INSERT INTO drivers(driver_id, full_name, first_name, last_name,
                name_acronym, broadcast_name, country_code, headshot_url,
                team_id, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (driver_id) DO NOTHING
            """,
            d.driver_id, d.full_name, d.first_name, d.last_name, d.name_acronym,
            d.broadcast_name, d.country_code, d.headshot_url,
            d.team.team_id if d.team else None,
            d.provenance.provenance_class.value,
        )
        if session_id and driver_number is not None:
            await self.pool.execute(
                """
                INSERT INTO session_drivers(session_id, driver_id, driver_number)
                VALUES($1,$2,$3)
                ON CONFLICT DO NOTHING
                """,
                session_id, d.driver_id, driver_number,
            )

    async def insert_lap(self, lap) -> bool:  # noqa: ANN001 Lap
        status = await self.pool.execute(
            """
            INSERT INTO laps(session_id, driver_number, lap_number, started_at,
                duration_s, sector1_s, sector2_s, sector3_s,
                i1_kph, i2_kph, st_kph, fl_kph, is_pit_out_lap,
                provenance_class, source_timestamp, ingestion_timestamp)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
            ON CONFLICT DO NOTHING
            """,
            lap.session_id, lap.driver_number, lap.lap_number, _ts(lap.started_at),
            lap.duration_s, lap.sector1_s, lap.sector2_s, lap.sector3_s,
            lap.speed_traps.i1_kph if lap.speed_traps else None,
            lap.speed_traps.i2_kph if lap.speed_traps else None,
            lap.speed_traps.st_kph if lap.speed_traps else None,
            lap.speed_traps.fl_kph if lap.speed_traps else None,
            lap.is_pit_out_lap, lap.provenance.provenance_class.value,
            _ts(lap.provenance.source_timestamp),
            _ts(lap.provenance.ingestion_timestamp),
        )
        return status.endswith("1")

    async def insert_sector(self, sec) -> bool:  # noqa: ANN001 SectorTime
        import json as _json

        status = await self.pool.execute(
            """
            INSERT INTO sectors(session_id, driver_number, lap_number,
                sector_index, time_s, segment_codes, provenance_class,
                source_timestamp, ingestion_timestamp)
            VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9)
            ON CONFLICT DO NOTHING
            """,
            sec.session_id, sec.driver_number, sec.lap_number, sec.sector_index,
            sec.time_s,
            _json.dumps(sec.segment_codes) if sec.segment_codes is not None else None,
            sec.provenance.provenance_class.value,
            _ts(sec.provenance.source_timestamp),
            _ts(sec.provenance.ingestion_timestamp),
        )
        return status.endswith("1")

    async def insert_car_samples_bulk(self, rows: list[tuple]) -> int:
        """Batched telemetry insert. Row tuple order matches SQL below."""
        if not rows:
            return 0
        await self.pool.executemany(
            """
            INSERT INTO telemetry_car(session_id, driver_number, ts, rpm,
                speed_kph, gear, throttle_pct, brake_pct, drs, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )
        return len(rows)

    async def insert_location_samples_bulk(self, rows: list[tuple]) -> int:
        if not rows:
            return 0
        await self.pool.executemany(
            """
            INSERT INTO telemetry_location(session_id, driver_number, ts, x, y, z,
                provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )
        return len(rows)

    async def insert_events_bulk(self, payloads: list[tuple]) -> int:
        import json as _json
        import uuid as _uuid

        if not payloads:
            return 0
        rows = [
            (
                _uuid.UUID(p["event_id"]), p["seq"], p["event_type"], p["category"],
                p["session_id"], p["driver_number"], p["origin"], p["source"],
                _ts(p["source_timestamp"]), _ts(p["ingestion_timestamp"]),
                p["provenance_class"], p["dedupe_key"],
                _json.dumps(p["payload"]),
            )
            for p in payloads
        ]
        await self.pool.executemany(
            """
            INSERT INTO events(event_id, seq, event_type, category, session_id,
                driver_number, origin, source, source_timestamp,
                ingestion_timestamp, provenance_class, dedupe_key, payload)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )
        return len(rows)

    async def insert_car_sample(self, m) -> bool:  # noqa: ANN001 TelemetryCarSample
        status = await self.pool.execute(
            """
            INSERT INTO telemetry_car(session_id, driver_number, ts, rpm,
                speed_kph, gear, throttle_pct, brake_pct, drs, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT DO NOTHING
            """,
            m.session_id, m.driver_number, _ts(m.ts), m.rpm, m.speed_kph, m.gear,
            m.throttle_pct, m.brake_pct, m.drs,
            m.provenance.provenance_class.value,
        )
        return status.endswith("1")

    async def insert_location_sample(self, m) -> bool:  # noqa: ANN001 TelemetryLocationSample
        status = await self.pool.execute(
            """
            INSERT INTO telemetry_location(session_id, driver_number, ts, x, y, z,
                provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT DO NOTHING
            """,
            m.session_id, m.driver_number, _ts(m.ts), m.x, m.y, m.z,
            m.provenance.provenance_class.value,
        )
        return status.endswith("1")

    async def upsert_stint(self, m) -> bool:  # noqa: ANN001 TyreStint
        status = await self.pool.execute(
            """
            INSERT INTO tyre_stints(session_id, driver_number, stint_number,
                compound, lap_start, lap_end, tyre_age_at_start, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (session_id, driver_number, stint_number) DO UPDATE SET
                compound = EXCLUDED.compound,
                lap_start = EXCLUDED.lap_start,
                lap_end = EXCLUDED.lap_end,
                tyre_age_at_start = EXCLUDED.tyre_age_at_start
            """,
            m.session_id, m.driver_number, m.stint_number, m.compound.value,
            m.lap_start, m.lap_end, m.tyre_age_at_start,
            m.provenance.provenance_class.value,
        )
        return True

    async def insert_pit_stop(self, m) -> bool:  # noqa: ANN001 PitStop
        status = await self.pool.execute(
            """
            INSERT INTO pit_stops(session_id, driver_number, ts, lap_number,
                lane_duration_s, stop_duration_s, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT DO NOTHING
            """,
            m.session_id, m.driver_number, _ts(m.ts), m.lap_number,
            m.lane_duration_s, m.stop_duration_s,
            m.provenance.provenance_class.value,
        )
        return status.endswith("1")

    async def insert_weather(self, m) -> bool:  # noqa: ANN001 WeatherPoint
        status = await self.pool.execute(
            """
            INSERT INTO weather_points(session_id, ts, air_temp_c, track_temp_c,
                humidity_pct, pressure_hpa, rainfall, wind_dir_deg,
                wind_speed_mps, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT DO NOTHING
            """,
            m.session_id, _ts(m.ts), m.air_temp_c, m.track_temp_c, m.humidity_pct,
            m.pressure_hpa, m.rainfall, m.wind_direction_deg, m.wind_speed_mps,
            m.provenance.provenance_class.value,
        )
        return status.endswith("1")

    async def insert_rcm(self, m) -> bool:  # noqa: ANN001 RaceControlEvent
        status = await self.pool.execute(
            """
            INSERT INTO race_control_messages(rcm_key, session_id, ts, category,
                flag, scope, marshal_sector, driver_number, lap_number,
                qualifying_phase, message, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT DO NOTHING
            """,
            m.rcm_key, m.session_id, _ts(m.ts), m.category.value, m.flag, m.scope,
            m.marshal_sector, m.driver_number, m.lap_number, m.qualifying_phase,
            m.message, m.provenance.provenance_class.value,
        )
        return status.endswith("1")

    async def insert_position(self, m) -> bool:  # noqa: ANN001 PositionUpdate
        status = await self.pool.execute(
            """
            INSERT INTO position_updates(session_id, driver_number, ts, position,
                provenance_class)
            VALUES($1,$2,$3,$4,$5)
            ON CONFLICT DO NOTHING
            """,
            m.session_id, m.driver_number, _ts(m.ts), m.position,
            m.provenance.provenance_class.value,
        )
        return status.endswith("1")

    async def insert_interval(self, m) -> bool:  # noqa: ANN001 TimingInterval
        status = await self.pool.execute(
            """
            INSERT INTO timing_intervals(session_id, driver_number, ts,
                gap_to_leader_s, gap_raw, interval_s, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT DO NOTHING
            """,
            m.session_id, m.driver_number, _ts(m.ts), m.gap_to_leader_s,
            m.gap_raw, m.interval_s, m.provenance.provenance_class.value,
        )
        return status.endswith("1")

    async def insert_lap_correction(self, m) -> bool:  # noqa: ANN001 LapCorrection
        """Record the correction explicitly, then apply the tombstone flag.

        Both steps are auditable: the correction row preserves reason/time/
        source link; the laps row only gains a deleted flag + timestamp.
        """
        status = await self.pool.execute(
            """
            INSERT INTO lap_corrections(session_id, driver_number, lap_number,
                kind, reason, deleted_time_raw, turn, rcm_key, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT DO NOTHING
            """,
            m.session_id, m.driver_number, m.lap_number, m.kind.value, m.reason,
            m.deleted_time_raw, m.turn, m.rcm_key,
            m.provenance.provenance_class.value,
        )
        if not status.endswith("1"):
            return False
        if m.kind.value == "LAP_DELETED":
            await self.pool.execute(
                """UPDATE laps SET deleted = TRUE, deleted_at = now()
                   WHERE session_id=$1 AND driver_number=$2 AND lap_number=$3""",
                m.session_id, m.driver_number, m.lap_number,
            )
        elif m.kind.value == "LAP_REINSTATED":
            await self.pool.execute(
                """UPDATE laps SET deleted = FALSE, deleted_at = NULL
                   WHERE session_id=$1 AND driver_number=$2 AND lap_number=$3""",
                m.session_id, m.driver_number, m.lap_number,
            )
        return True

    async def insert_race_result(self, m) -> bool:  # noqa: ANN001 RaceResult
        status = await self.pool.execute(
            """
            INSERT INTO race_results(session_id, driver_ref, driver_number,
                family_name, constructor_ref, position, status_text, points,
                laps_completed, finish_time_raw, fastest_lap_raw, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT (session_id, driver_ref) DO UPDATE SET
                position=EXCLUDED.position, status_text=EXCLUDED.status_text,
                points=EXCLUDED.points
            """,
            m.session_id, m.driver_ref, m.driver_number, m.family_name,
            m.constructor_ref, m.position, m.status_text, m.points,
            m.laps_completed, m.finish_time_raw, m.fastest_lap_raw,
            m.provenance.provenance_class.value,
        )
        return True

    async def insert_quali_result(self, m) -> bool:  # noqa: ANN001 QualifyingResult
        status = await self.pool.execute(
            """
            INSERT INTO qualifying_results(session_id, driver_ref, driver_number,
                constructor_ref, position, q1_raw, q2_raw, q3_raw, provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (session_id, driver_ref) DO UPDATE SET
                position=EXCLUDED.position, q1_raw=EXCLUDED.q1_raw,
                q2_raw=EXCLUDED.q2_raw, q3_raw=EXCLUDED.q3_raw
            """,
            m.session_id, m.driver_ref, m.driver_number, m.constructor_ref,
            m.position, m.q1_raw, m.q2_raw, m.q3_raw,
            m.provenance.provenance_class.value,
        )
        return True

    async def insert_standings_entry(self, m) -> bool:  # noqa: ANN001 StandingsEntry
        status = await self.pool.execute(
            """
            INSERT INTO standings_entries(season, round_after, driver_ref,
                family_name, constructor_ref, position, points, wins,
                provenance_class)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (season, round_after, driver_ref) DO UPDATE SET
                position=EXCLUDED.position, points=EXCLUDED.points,
                wins=EXCLUDED.wins
            """,
            m.season, m.round_after if m.round_after is not None else -1,
            m.driver_ref, m.family_name, m.constructor_ref, m.position,
            m.points, m.wins, m.provenance.provenance_class.value,
        )
        return True

    # ------------------------------------------------- telemetry queries ----

    async def telemetry_car_range(
        self, session_id: str, driver_number: int,
        start, end) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT ts, rpm, speed_kph, gear, throttle_pct, brake_pct, drs
            FROM telemetry_car
            WHERE session_id=$1 AND driver_number=$2 AND ts BETWEEN $3 AND $4
            ORDER BY ts
            """,
            session_id, driver_number, _ts(start), _ts(end),
        )
        return [dict(r) for r in rows]

    async def telemetry_location_range(
        self, session_id: str, driver_number: int,
        start, end) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT ts, x, y, z FROM telemetry_location
            WHERE session_id=$1 AND driver_number=$2 AND ts BETWEEN $3 AND $4
            ORDER BY ts
            """,
            session_id, driver_number, _ts(start), _ts(end),
        )
        return [dict(r) for r in rows]

    async def lap_window(self, session_id: str, driver_number: int,
                         lap_number: int) -> tuple[Any, Any] | None:
        row = await self.pool.fetchrow(
            "SELECT started_at, duration_s FROM laps "
            "WHERE session_id=$1 AND driver_number=$2 AND lap_number=$3",
            session_id, driver_number, lap_number,
        )
        if not row or row["started_at"] is None:
            return None
        from datetime import timedelta

        start = row["started_at"]
        end = (start + timedelta(seconds=row["duration_s"])
               if row["duration_s"] else start + timedelta(minutes=3))
        return start, end

    async def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT session_id, provider, year, session_type, session_name,"
            " circuit_short_name, country_code, date_start, status"
            " FROM sessions ORDER BY date_start DESC NULLS LAST LIMIT $1", limit)
        return [dict(r) for r in rows]

    async def session_driver_list(self, session_id: str) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """SELECT sd.driver_number, d.driver_id, d.full_name,
                      d.name_acronym, t.display_name AS team
               FROM session_drivers sd JOIN drivers d USING(driver_id)
               LEFT JOIN teams t ON t.team_id = d.team_id
               WHERE sd.session_id=$1 ORDER BY sd.driver_number""",
            session_id,
        )
        return [dict(r) for r in rows]

    async def insert_event(self, env) -> None:  # noqa: ANN001 Envelope
        import json as _json
        import uuid as _uuid

        await self.pool.execute(
            """
            INSERT INTO events(event_id, seq, event_type, category, session_id,
                driver_number, origin, source, source_timestamp,
                ingestion_timestamp, provenance_class, dedupe_key, payload)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)
            ON CONFLICT DO NOTHING
            """,
            _uuid.UUID(env.event_id), env.seq, env.event_type, env.category,
            env.session_id, env.driver_number, env.origin, env.source,
            _ts(env.source_timestamp), _ts(env.ingestion_timestamp),
            env.provenance_class.value, env.dedupe_key,
            _json.dumps(json.loads(env.model_dump_json())["payload"]),
        )

    async def save_quality_report(self, session_id: str, mode: str, report: dict) -> None:
        import json as _json

        await self.pool.execute(
            "INSERT INTO quality_reports(session_id, mode, report) VALUES($1,$2,$3::jsonb)",
            session_id, mode, _json.dumps(report),
        )

    async def execute_log_state(self, session_id: str, projection) -> None:
        """Persist a session-phase transition (best-effort)."""
        import json as _json

        last = projection.history[-1] if projection.history else None
        await self.pool.execute(
            """INSERT INTO provider_health_log(provider, session_id, event, detail)
               VALUES('pipeline', $1, $2, $3::jsonb)""",
            session_id,
            f"phase:{projection.phase.value}",
            _json.dumps({
                "from": last.from_phase.value if last else None,
                "trigger": last.trigger if last else None,
            }),
        )

    # ---------------------------------------------------------- queries -----

    async def session_summary(self, session_id: str) -> dict[str, Any]:
        q = "SELECT * FROM sessions WHERE session_id = $1"
        row = await self.pool.fetchrow(q, session_id)
        return dict(row) if row else {}

    async def counts(self, session_id: str) -> dict[str, int]:
        tables = {
            "laps": "laps", "sectors": "sectors", "telemetry_car": "telemetry_car",
            "telemetry_location": "telemetry_location", "tyre_stints": "tyre_stints",
            "pit_stops": "pit_stops", "weather_points": "weather_points",
            "race_control_messages": "race_control_messages",
            "position_updates": "position_updates",
            "timing_intervals": "timing_intervals", "events": "events",
        }
        out: dict[str, int] = {}
        for label, table in tables.items():
            n = await self.pool.fetchval(
                f"SELECT count(*) FROM {table} WHERE session_id = $1", session_id
            )
            out[label] = int(n or 0)
        return out
