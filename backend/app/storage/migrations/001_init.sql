-- 001_init.sql - Phase 1 canonical schema (PostgreSQL 15+ / TimescaleDB compatible)
--
-- Indexing decisions:
-- * Natural keys get UNIQUE constraints that double as dedupe guards
--   (idempotent upserts: ON CONFLICT DO NOTHING).
-- * Telemetry tables are append-only, high-rate; PK is a bigint identity and
--   lookups use the (session_id, driver_number, ts) composite index. Rows are
--   deliberately NOT over-normalized - one row = one source sample.
-- * events table stores the full canonical envelope for audit + replay parity.
-- * TimescaleDB hypertable conversion is optional (002_timescale_optional.sql).

CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS schema_migrations (
    name        TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- sessions --
CREATE TABLE IF NOT EXISTS sessions (
    session_id           TEXT PRIMARY KEY,             -- "openf1:11353"
    provider             TEXT NOT NULL,
    provider_session_key TEXT NOT NULL,
    provider_meeting_key TEXT,
    meeting_name         TEXT,
    year                 INTEGER,
    session_type         TEXT NOT NULL DEFAULT 'UNKNOWN',
    session_name         TEXT,
    circuit_short_name   TEXT,
    country_code         TEXT,
    country_name         TEXT,
    location             TEXT,
    gmt_offset           TEXT,
    date_start           TIMESTAMPTZ,
    date_end             TIMESTAMPTZ,
    is_cancelled         BOOLEAN NOT NULL DEFAULT FALSE,
    status               TEXT NOT NULL DEFAULT 'UNKNOWN',
    provenance_class     CHAR(1) NOT NULL,
    source_timestamp     TIMESTAMPTZ,
    ingestion_timestamp  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_session_key)
);

CREATE INDEX IF NOT EXISTS ix_sessions_year ON sessions (year);

-- ------------------------------------------------------------------- teams --
CREATE TABLE IF NOT EXISTS teams (
    team_id       TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    colour_hex    TEXT,
    provenance_class CHAR(1) NOT NULL DEFAULT 'A'
);

-- ----------------------------------------------------------------- drivers --
CREATE TABLE IF NOT EXISTS drivers (
    driver_id      TEXT PRIMARY KEY,                  -- "lando-norris-4"
    full_name      TEXT NOT NULL,
    first_name     TEXT,
    last_name      TEXT,
    name_acronym   TEXT,
    broadcast_name TEXT,
    country_code   TEXT,
    headshot_url   TEXT,
    team_id        TEXT REFERENCES teams(team_id),
    provenance_class CHAR(1) NOT NULL DEFAULT 'A'
);

CREATE TABLE IF NOT EXISTS session_drivers (
    session_id    TEXT NOT NULL REFERENCES sessions(session_id),
    driver_id     TEXT NOT NULL REFERENCES drivers(driver_id),
    driver_number INTEGER NOT NULL,
    PRIMARY KEY (session_id, driver_id)
);
CREATE INDEX IF NOT EXISTS ix_session_drivers_num ON session_drivers (session_id, driver_number);

-- -------------------------------------------------------------------- laps --
CREATE TABLE IF NOT EXISTS laps (
    session_id      TEXT NOT NULL REFERENCES sessions(session_id),
    driver_number   INTEGER NOT NULL,
    lap_number      INTEGER NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    duration_s      DOUBLE PRECISION,
    sector1_s       DOUBLE PRECISION,
    sector2_s       DOUBLE PRECISION,
    sector3_s       DOUBLE PRECISION,
    i1_kph          INTEGER,
    i2_kph          INTEGER,
    st_kph          INTEGER,
    fl_kph          INTEGER,
    is_pit_out_lap  BOOLEAN,
    deleted         BOOLEAN NOT NULL DEFAULT FALSE,
    provenance_class CHAR(1) NOT NULL,
    source_timestamp TIMESTAMPTZ,
    ingestion_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, driver_number, lap_number)
);

CREATE INDEX IF NOT EXISTS ix_laps_session ON laps (session_id, lap_number);
CREATE INDEX IF NOT EXISTS ix_laps_ts ON laps (session_id, started_at);

-- -------------------------------------------------------------- sectors ----
-- Mini-segment code arrays stored verbatim as JSONB; interpretation deferred.
CREATE TABLE IF NOT EXISTS sectors (
    session_id      TEXT NOT NULL,
    driver_number   INTEGER NOT NULL,
    lap_number      INTEGER NOT NULL,
    sector_index    SMALLINT NOT NULL CHECK (sector_index IN (1,2,3)),
    time_s          DOUBLE PRECISION,
    segment_codes   JSONB,
    provenance_class CHAR(1) NOT NULL,
    source_timestamp TIMESTAMPTZ,
    ingestion_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, driver_number, lap_number, sector_index)
);

-- ------------------------------------------------------- telemetry (car) ---
CREATE TABLE IF NOT EXISTS telemetry_car (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    TEXT NOT NULL,
    driver_number INTEGER NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    rpm           INTEGER,
    speed_kph     INTEGER,
    gear          INTEGER,
    throttle_pct  DOUBLE PRECISION,
    brake_pct     DOUBLE PRECISION,
    drs           INTEGER,
    provenance_class CHAR(1) NOT NULL,
    UNIQUE (session_id, driver_number, ts)
);
CREATE INDEX IF NOT EXISTS ix_telemetry_car_lookup ON telemetry_car (session_id, driver_number, ts);

-- --------------------------------------------------- telemetry (location) --
CREATE TABLE IF NOT EXISTS telemetry_location (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    TEXT NOT NULL,
    driver_number INTEGER NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    x             DOUBLE PRECISION,
    y             DOUBLE PRECISION,
    z             DOUBLE PRECISION,
    provenance_class CHAR(1) NOT NULL,
    UNIQUE (session_id, driver_number, ts)
);
CREATE INDEX IF NOT EXISTS ix_telemetry_loc_lookup ON telemetry_location (session_id, driver_number, ts);

-- ------------------------------------------------------------ tyre stints --
CREATE TABLE IF NOT EXISTS tyre_stints (
    session_id        TEXT NOT NULL,
    driver_number     INTEGER NOT NULL,
    stint_number      INTEGER NOT NULL,
    compound          TEXT NOT NULL DEFAULT 'UNKNOWN',
    lap_start         INTEGER,
    lap_end           INTEGER,
    tyre_age_at_start INTEGER,
    provenance_class  CHAR(1) NOT NULL,
    ingestion_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, driver_number, stint_number)
);

-- ---------------------------------------------------------------- pit stops --
CREATE TABLE IF NOT EXISTS pit_stops (
    session_id      TEXT NOT NULL,
    driver_number   INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    lap_number      INTEGER,
    lane_duration_s DOUBLE PRECISION,
    stop_duration_s DOUBLE PRECISION,
    provenance_class CHAR(1) NOT NULL,
    PRIMARY KEY (session_id, driver_number, ts)
);

-- ---------------------------------------------------------------- weather --
CREATE TABLE IF NOT EXISTS weather_points (
    session_id      TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    air_temp_c      DOUBLE PRECISION,
    track_temp_c    DOUBLE PRECISION,
    humidity_pct    DOUBLE PRECISION,
    pressure_hpa    DOUBLE PRECISION,
    rainfall        BOOLEAN,
    wind_dir_deg    INTEGER,
    wind_speed_mps  DOUBLE PRECISION,
    provenance_class CHAR(1) NOT NULL,
    PRIMARY KEY (session_id, ts)
);

-- ------------------------------------------------------------ race control --
CREATE TABLE IF NOT EXISTS race_control_messages (
    rcm_key         TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    category        TEXT NOT NULL DEFAULT 'UNKNOWN',
    flag            TEXT,
    scope           TEXT,
    marshal_sector  INTEGER,   -- marshal post number (>3 observed); NOT timing sector
    driver_number   INTEGER,
    lap_number      INTEGER,
    qualifying_phase TEXT,
    message         TEXT NOT NULL,
    provenance_class CHAR(1) NOT NULL,
    PRIMARY KEY (session_id, rcm_key)
);
CREATE INDEX IF NOT EXISTS ix_rcm_ts ON race_control_messages (session_id, ts);

-- ------------------------------------------------------ positions/gaps -----
CREATE TABLE IF NOT EXISTS position_updates (
    session_id    TEXT NOT NULL,
    driver_number INTEGER NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    position      INTEGER NOT NULL,
    provenance_class CHAR(1) NOT NULL,
    PRIMARY KEY (session_id, driver_number, ts)
);

CREATE TABLE IF NOT EXISTS timing_intervals (
    session_id      TEXT NOT NULL,
    driver_number   INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    gap_to_leader_s DOUBLE PRECISION,
    gap_raw         TEXT,          -- verbatim non-numeric upstream value ('+1 LAP')
    interval_s      DOUBLE PRECISION,
    provenance_class CHAR(1) NOT NULL,
    PRIMARY KEY (session_id, driver_number, ts)
);

-- ----------------------------------------------- canonical event log -------
CREATE TABLE IF NOT EXISTS events (
    event_id         UUID PRIMARY KEY,
    seq              INTEGER,
    event_type       TEXT NOT NULL,
    category         TEXT NOT NULL DEFAULT 'domain',
    session_id       TEXT NOT NULL,
    driver_number    INTEGER,
    origin           TEXT NOT NULL DEFAULT 'live',
    source           TEXT NOT NULL,
    source_timestamp TIMESTAMPTZ,
    ingestion_timestamp TIMESTAMPTZ NOT NULL,
    provenance_class CHAR(1) NOT NULL,
    dedupe_key       TEXT,
    payload          JSONB NOT NULL,
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_events_dedupe ON events (coalesce(dedupe_key, event_id::text), session_id);
CREATE INDEX IF NOT EXISTS ix_events_type ON events (session_id, event_type, seq);

-- --------------------------------------------------------- quality reports --
CREATE TABLE IF NOT EXISTS quality_reports (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode        TEXT NOT NULL,
    report      JSONB NOT NULL
);
