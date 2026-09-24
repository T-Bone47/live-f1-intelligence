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

Returns per-driver series plus an alignment block. The series are NOT
distance-aligned in either mode, and the block says so:
- mode=lap_time_window, valid=false when ?lap= given - each driver's series
  is narrowed to that driver's own lap time window, nothing more
- mode=timestamp, valid=false otherwise

Corrected in Phase 10.2 validation: this previously claimed
mode=normalized_lap_progress, valid=true, but no normalization was ever
computed - and the route was in fact unreachable (every request 422'd,
shadowed by /telemetry/{driver_number}; fixed with an :int path
convertor) and would have crashed if reached (.json() on a server-side
JSONResponse). The distance-synchronized comparison exists in
app.analysis.lap_comparison but is not routed yet.

## Storage

Structured columns (Phase-1 schema) + composite indexes
(session_id, driver_number, ts DESC); Timescale hypertables/compression when
the extension exists (migration 005). Retention: nothing auto-deletes.
