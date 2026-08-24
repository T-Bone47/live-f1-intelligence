# TELEMETRY_STREAMING.md

Raw telemetry is ~3.5 Hz x 20 cars. Delivery policy:

1. SUBSCRIPTION REQUIRED: telemetry frames go only to clients that sent
   subscribe {telemetry_drivers:[...]}.
2. LATEST-WINS COALESCING: per driver one pending sample; newer arrivals
   replace unflushed older ones (stale drops counted as
   telemetry_dropped_stale).
3. CADENCE: flush interval default 0.2 s (5 Hz), configurable; independent of
   arrival rate.
4. FIELDS: speed_kph, rpm, gear, throttle_pct, brake_pct, drs, x/y/z - exactly
   as delivered upstream; missing channels stay absent (drs is null in real
   data; no fabricated zeros).
5. FRAMES: kind=telemetry with driver number + samples array; sequenced like
   every frame so gaps are detectable.

Backpressure interplay: telemetry frames are first-shed under client queue
pressure (after deltas, before critical events).
