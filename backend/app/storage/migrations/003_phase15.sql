-- 003_phase15.sql - Phase 1.5: corrections, reference/history, provider quality

-- Explicit lap tombstone/correction ledger. The laps table's `deleted` flag
-- is a PROJECTION of this ledger (applied via insert_lap_correction); the
-- original lap row is never modified beyond the flag.
CREATE TABLE IF NOT EXISTS lap_corrections (
    session_id      TEXT NOT NULL,
    driver_number   INTEGER NOT NULL,
    lap_number      INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('LAP_DELETED','LAP_REINSTATED')),
    reason          TEXT,
    deleted_time_raw TEXT,
    turn            INTEGER,
    rcm_key         TEXT,
    provenance_class CHAR(1) NOT NULL DEFAULT 'A',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, driver_number, lap_number, kind, rcm_key)
);
CREATE INDEX IF NOT EXISTS ix_lapcorr_session ON lap_corrections (session_id);

ALTER TABLE laps ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Reference/history tables (Jolpica / FastF1 / F1DB class-B data)
CREATE TABLE IF NOT EXISTS race_results (
    session_id      TEXT NOT NULL,
    driver_ref      TEXT NOT NULL,
    driver_number   INTEGER,
    family_name     TEXT,
    constructor_ref TEXT,
    position        INTEGER,
    status_text     TEXT,
    points          DOUBLE PRECISION,
    laps_completed  INTEGER,
    finish_time_raw TEXT,
    fastest_lap_raw TEXT,
    provenance_class CHAR(1) NOT NULL DEFAULT 'B',
    PRIMARY KEY (session_id, driver_ref)
);

CREATE TABLE IF NOT EXISTS qualifying_results (
    session_id      TEXT NOT NULL,
    driver_ref      TEXT NOT NULL,
    driver_number   INTEGER,
    constructor_ref TEXT,
    position        INTEGER,
    q1_raw          TEXT,
    q2_raw          TEXT,
    q3_raw          TEXT,
    provenance_class CHAR(1) NOT NULL DEFAULT 'B',
    PRIMARY KEY (session_id, driver_ref)
);

CREATE TABLE IF NOT EXISTS standings_entries (
    season          INTEGER NOT NULL,
    round_after     INTEGER NOT NULL DEFAULT -1,
    driver_ref      TEXT NOT NULL,
    family_name     TEXT,
    constructor_ref TEXT,
    position        INTEGER,
    points          DOUBLE PRECISION,
    wins            INTEGER,
    provenance_class CHAR(1) NOT NULL DEFAULT 'B',
    PRIMARY KEY (season, round_after, driver_ref)
);

CREATE TABLE IF NOT EXISTS provider_health_log (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider     TEXT NOT NULL,
    session_id   TEXT,
    event        TEXT NOT NULL,   -- connected|failed|failover|recovered
    detail       JSONB
);
