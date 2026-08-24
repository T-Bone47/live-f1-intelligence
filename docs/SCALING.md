# SCALING.md

## Measured load test (Phase 3 acceptance)

Workload: full 2026 Dutch GP recording replayed at MAX speed through ingest +
analysis + gateway in ONE process; N websocket clients on localhost for 10 s.

| Clients | Completed | Aggregate frames/s | WS p50 latency | Drops | Evictions |
|---|---|---|---|---|---|
| 10  | 10  | 70    | 14.9 ms  | 0 | 0 |
| 50  | 50  | 395   | 79.0 ms  | 0 | 0 |
| 100 | 100 | 994   | 129.7 ms | 0 | 0 |

CPU ~95% in all runs BY CONSTRUCTION (max-speed replay saturates the shared
loop). Real live input peaks near ~200 msg/s - roughly 30x lighter than this
worst-case harness - so production headroom at 100 clients is large.

## Interpretation & scaling triggers

Latency grows linearly with fanout once CPU-saturated: first remedy is
separating replay/ingest from serving processes (already supported); second
is Redis pub/sub replication across stateless gateways (slot implemented).
Zero drops/evictions across the ladder shows the queue policy holds under
saturation. Re-run: python scripts/load_test_ws.py recordings/<name> --clients N
