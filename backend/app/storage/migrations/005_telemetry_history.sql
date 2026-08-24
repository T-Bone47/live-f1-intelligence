-- 005_telemetry_history.sql - Phase 4: time-series query support
--
-- Schema note: telemetry_car / telemetry_location already exist as structured
-- columns (Phase 1) - deliberately NOT JSON blobs. This migration adds the
-- query-pattern indexes and documents the time-series strategy.
--
-- Query patterns optimized:
--   * driver session range : (session_id, driver_number, ts)
--   * lap alignment        : laps(started_at) join window on ts per driver
--   * latest live values   : reverse scan on the same composite index
--   * comparison           : two range scans + client/server-side alignment
--
-- TimescaleDB: 002_timescale_optional.sql already converts both tables to
-- hypertables (ts) when available. Chunk sizing guidance for Timescale:
--   chunk_time_interval => 1 hour per session-day of live capture
--   (default adaptive chunking is acceptable at Phase-4 volumes).
--
-- Compression (Timescale only, guarded below): segmentby session_id,
-- driver_number; orderby ts - typical >10x reduction on these columns.
-- Retention: keep RAW forever for recorded/archive sessions; optional
-- continuous_aggregate 'telemetry_1s' may be added in a later phase if
-- dashboard range queries need it. Nothing here deletes data by default.

CREATE INDEX IF NOT EXISTS ix_telemetry_car_lap_window
    ON telemetry_car (session_id, driver_number, ts DESC);

CREATE INDEX IF NOT EXISTS ix_telemetry_loc_lap_window
    ON telemetry_location (session_id, driver_number, ts DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        -- Compression requires Timescale; failures here are non-fatal and
        -- simply leave plain PG behavior in place.
        BEGIN
            ALTER TABLE telemetry_car SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'session_id, driver_number',
                timescaledb.compress_orderby = 'ts'
            );
            PERFORM add_compression_policy('telemetry_car', INTERVAL '30 days');
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'compression policy skipped: %', SQLERRM;
        END;
    END IF;
END $$;

-- Frequency presets are enforced application-side (LTTB), not in SQL:
--   RAW    : no downsampling (max 20-minute windows enforced by API)
--   HIGH   : ~2 Hz target
--   MEDIUM : ~1 Hz target
--   LOW    : ~0.25 Hz target
