# LIVE_DATA_STRATEGY.md

| | |
|---|---|
| Status | Phase 1.5 |
| Scope | Source priorities, reconciliation, failover, session state, corrections, and the live-window acceptance runbook |

---

## 1. WHAT WE KNOW vs WHAT WE CANNOT ACCESS

**Verified (see PROVIDER_COMPARISON §2 for the ledger):**
- OpenF1 delivers complete session data via REST (historical proven; live
  requires their paid tier).
- The F1 livetiming SignalR Core feed accepts negotiate/handshake/subscribe
  without credentials today and serves a full snapshot of subscribed topics.
- Jolpica covers schedule/results/standings; FastF1 covers high-resolution
  post-session analysis; F1DB is an active reference dataset.

**Cannot access / cannot rely on:**
- No legitimate commercial license for the feed exists at hobby scale.
- SignalR token-less access is a current privilege, not a right — auth can
  appear any time; provider carries pluggable bearer-token support.
- Live-window latencies: **not measured yet** (no live window occurred during
  Phase 1.5). No real-time claims until `live_latency_report.py` prints class-A
  percentiles from a real session.
- Channels that simply do not exist publicly: tyre temps, fuel/ERS, team
  encrypted strategy comms, precise lateral GPS.

## 2. Recommended source priority matrix

Implemented in `app/core/source_policy.py::RECOMMENDED_PRIORITY`
(configurable; nothing hard-codes providers into consumers):

| Domain | Priority order |
|---|---|
| Timing/laps, telemetry, GPS, intervals | SignalR → OpenF1 → (historical) FastF1 |
| Stints/pits/weather/race control/positions | SignalR → OpenF1 → FastF1 |
| Results (race/quali), standings | Jolpica |
| Schedule | Jolpica → OpenF1 |
| Reference metadata (drivers/teams/circuits history) | F1DB (planned import) |
| Replay | provider-independent recording |

Rationale: direct feed wins wherever it demonstrably streams (lowest latency,
richest topics); OpenF1 is the proven fallback; FastF1 never competes live —
it serves backtesting/validation with class-B data only.

## 3. Multi-source reconciliation policy

Implemented in `ReconciliationPolicy` (unit-tested). Principles:

1. **Never merge or average.** A fact has one winner per instant.
2. Canonical identity keys decide "same fact": (session, driver, lap/ts).
3. Resolution outcomes:
   - values equal → PRIMARY wins;
   - primary missing → secondary fills (FRESHER), provenance kept honest;
   - timestamps outside freshness window (default ±2 s) → fresher observation
     wins;
   - same-instant disagreement → CONFLICT: primary value served, challenger
     retained as alternate with its own provenance, conflict counter raised to
     quality metrics for review.
4. Every stored value keeps `source` + `provenance_class`; alternates are
   never silently discarded (audit requirement from charter rule 11).

## 4. Failover design (deliberately minimal)

`ProviderChainRunner` (tested): ordered factories per domain chain.
- Advance on: provider exception, zero-delivery exhaustion, or stall watchdog
  (>90 s without items while claiming live).
- Promote on first successful delivery.
- When all options fail: channel marked unavailable. **No fabrication, ever**
  — telemetry loss stays visible as missing data.
- Current wiring: OpenF1-only by default; `[signalr, openf1]` chain available
  behind `SIGNALR_ENABLED=true`.

## 5. Session-state projection

`app/core/session_state.py` folds RCM/session facts into one phase:
`SCHEDULED FORMATION LIVE SUSPENDED RED_FLAG SAFETY_CAR VSC CHEQUERED
FINISHED UNKNOWN`, plus track-flag detail and a full transition history
(replay-auditable). Verified against the real Dutch-GP message corpus
(GREEN→YELLOW→SAFETY_CAR→…→CHEQUERED). Wired into record_session; transitions
are logged and persisted (`provider_health_log`). Conservative matching:
unknown messages never mutate phase.

## 6. Lap deletion / correction model

- `LapCorrection` canonical record + `lap.deleted` / `lap.reinstated` events
  derived from verified RCM texts ("CAR 27 (HUL) TIME 1:23.646 DELETED - …").
- Ledger table `lap_corrections` preserves reason/time/turn/source link;
  `laps.deleted` flag is an explicit projection applied by the repository —
  original lap rows are never rewritten silently.
- Backfilled against the real race: 10 corrections applied, e.g.
  `#27 L5 83.646s -> DELETED (TRACK LIMITS AT TURN 3)`.

## 7. Provider-level data-quality

Quality monitor now tracks per-provider channel counts, malformed/duplicate
counters and latency samples; reports embed a `providers:{...}` section so two
providers can be compared over the same session when legitimately possible.

## 8. LIVE-WINDOW ACCEPTANCE RUNBOOK (pending next session)

No supported live session occurred during Phase 1.5 (Dutch GP ended
2026-08-23; next round outside the phase window). Runbook for the next one:

```
# T-30 min (before session start)
$env:SIGNALR_ENABLED = "true"          # optional: exercise direct feed
python scripts\record_session.py --ref latest --max-seconds <duration+60>
# after chequered flag:
python scripts\live_latency_report.py openf1:<session_key>
```

Report requirements (per Phase 1.5): min/mean/p50/p95/p99/max of
source→ingestion latency, separately for timing, telemetry, position, sectors,
race control, weather — measured values only. The tool refuses to invent
numbers: with zero class-A samples it prints "VERDICT: no live latency
samples".
