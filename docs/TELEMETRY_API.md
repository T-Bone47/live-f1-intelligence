# TELEMETRY_API.md

Canonical telemetry query endpoints (Phase 4). Responses contain stored
canonical values only; missing channels stay absent.

## GET /api/v1/sessions/{sid}/telemetry/{driver}

Query params:
- start / end : ISO-8601 UTC range (overrides lap)
- lap         : align window to that drivers lap N
- frequency   : RAW | HIGH | MEDIUM(300 pts) | LOW(120) - LTTB downsampling;
                RAW capped to 20-minute windows
- fields      : comma list e.g. speed,throttle,brake,gear,rpm,drs,gps

Response:
{ session_id, driver_number, frequency, lap, window{start,end},
  provenance{class A|B}, series: { speed:[{ts,value}...], gps:[{ts,x,y,z}] } }

404 when no stored telemetry exists for the pair - never empty-but-fake data.

## GET /api/v1/sessions/{sid}/telemetry/compare?drivers=16,55[&lap=N]

Returns per-driver series plus an alignment block:
- mode=normalized_lap_progress, valid=true when ?lap= given
- mode=timestamp, valid=false otherwise (explicitly flagged: two different
  laps are NOT claimed comparable without lap alignment).

## Storage

Structured columns (Phase-1 schema) + composite indexes
(session_id, driver_number, ts DESC); Timescale hypertables/compression when
the extension exists (migration 005). Retention: nothing auto-deletes.
