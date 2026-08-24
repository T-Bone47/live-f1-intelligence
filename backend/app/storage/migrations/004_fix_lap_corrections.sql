-- 004_fix_lap_corrections.sql
-- 003 made rcm_key effectively NOT NULL by including it in the PRIMARY KEY
-- (Postgres enforces NOT NULL on PK columns). Corrections may legitimately
-- arrive without an RCM link (e.g., manual backfill) - rebuild with a
-- surrogate key and an expression-based unique index instead.

DROP TABLE IF EXISTS lap_corrections;

CREATE TABLE IF NOT EXISTS lap_corrections (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      TEXT NOT NULL,
    driver_number   INTEGER NOT NULL,
    lap_number      INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('LAP_DELETED','LAP_REINSTATED')),
    reason          TEXT,
    deleted_time_raw TEXT,
    turn            INTEGER,
    rcm_key         TEXT,
    provenance_class CHAR(1) NOT NULL DEFAULT 'A',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_lapcorr_identity
    ON lap_corrections (session_id, driver_number, lap_number, kind,
                        COALESCE(rcm_key, ''));
CREATE INDEX IF NOT EXISTS ix_lapcorr_session
    ON lap_corrections (session_id);
