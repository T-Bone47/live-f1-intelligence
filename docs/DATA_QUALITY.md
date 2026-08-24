# DATA_QUALITY.md

The data-quality monitor is developer instrumentation for proving the
pipeline's honesty — what arrived, how fast, how broken. It is not the
product UI.

---

## 1. What is measured

Per ingestion run (live or historical):

| Metric | Source |
|---|---|
| Session detected / status / start | resolved SessionInfo |
| Drivers detected | distinct driver_numbers seen |
| Per-channel event counts | lap, sector, tyre, pit, weather, rcm, position, timing, telemetry |
| Telemetry availability per driver | distinct drivers in telemetry channel |
| Malformed events | normalization failures (dropped + logged) |
| Duplicate events | dedupe_key suppressions |
| Reconnects | transport-level retries |
| Latency min/avg/p50/p95/max | ingestion_timestamp − source_timestamp |

Latency is reported separately for **class A only** (true live). Historical
backfills show source age instead — backfill speed must never be mistaken for
live latency.

## 2. Sample report (real run)

```
============================================================
DATA QUALITY
============================================================
Session: Race (NED)
Status : FINISHED
Start  : 2026-08-23T13:00:00+00:00
Drivers: 22
Lap        : 1373 events
Sector     : 4119 events
Tyres      : 435 events
Pit        : 65 events
Weather    : 183 events
RaceControl: 329 events
Position   : 586 events
Intervals  : 30613 events
Telemetry (car): 22 drivers with samples
Latency: HISTORICAL BACKFILL (not live) - avg source age 6.6h
Malformed: 0  Duplicates: 470  Reconnects: 0
============================================================
```

## 3. How to view

```powershell
# during/after record_session: printed automatically + saved to
#   recordings/<name>/quality.json and DB quality_reports table
python scripts/data_quality.py openf1:11353          # latest stored report
python scripts/data_quality.py --file recordings\openf1-11353-race\quality.json
```

## 4. Interpreting counts

- **Duplicates > 0 is healthy** in live polling (upstream re-delivers; dedupe
  proves idempotency). Large spikes suggest upstream instability.
- **Malformed should stay ~0.** Non-zero means an unmapped upstream variant —
  check WARNING logs (`malformed ... item dropped`), fix the mapper, add a
  fixture-based regression test.
- **Missing channels**: consult `provider.capabilities()` first — absence may
  be a declared limitation, not a fault.
- Interval counts include lapped-car rows whose `gap_to_leader` is the string
  `'+1 LAP'` (stored verbatim in `gap_raw`, numeric column stays NULL).

## 5. Phase-1 latency findings

No live-session measurement was possible during Phase 1 acceptance (the
acceptance session was outside its live window; OpenF1 free tier restricts
in-window access). The measurement machinery is implemented, tested with
synthetic delays, and will produce class-A p50/p95 stats on the first live
run. Do not quote any "real-time" claim until those numbers exist.
