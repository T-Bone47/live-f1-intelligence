-- 002_timescale_optional.sql
-- OPTIONAL TimescaleDB conversion. Guarded: the migration runner catches
-- failures here and records the migration as SKIPPED (not applied) when the
-- extension is unavailable, leaving the plain-PG schema fully functional.

DO $$
DECLARE
    has_tsdb BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb')
        INTO has_tsdb;
    IF has_tsdb THEN
        CREATE EXTENSION IF NOT EXISTS timescaledb;
        PERFORM create_hypertable('telemetry_car', 'ts', if_not_exists => TRUE,
                                  migrate_data => TRUE);
        PERFORM create_hypertable('telemetry_location', 'ts', if_not_exists => TRUE,
                                  migrate_data => TRUE);
    ELSE
        RAISE NOTICE 'timescaledb not available - skipping hypertable conversion';
    END IF;
END $$;
