# ANALYSIS_ENGINE.md

| | |
|---|---|
| Status | Phase 2 |
| Scope | The deterministic intelligence layer: architecture, contracts, benchmarks |

---

## 1. Position in the system

```
canonical envelopes (any provider / replay)
        │  EventBus subscriber ("analysis", opt-in via F1_ANALYZE=1)
        ▼
AnalysisEngine.process_envelope()      backend/app/analysis/__init__.py
        │  dispatch by payload model type (_HANDLERS)
        ├─▶ RaceControlState   (flag timeline + phase)
        ├─▶ TimingEngine       (laps, PB/SB, positions, gap series)
        ├─▶ SectorEngine       (PB/SB/purple/green/yellow, theoretical)
        ├─▶ LapClassifier      (flags + class; raw data never modified)
        ├─▶ PaceEngine         (rolling windows, trends, clean air)
        ├─▶ StintEngine        (lap ledger → stint assignment → degradation)
        ├─▶ GapEngine          (pair closing rates/trends)
        ├─▶ BattleDetector     (deterministic FSM)
        ├─→ StrategyPrimitives (pit windows/undercut/rejoin inputs)
        ├─▶ WeatherEngine      (trends + threshold crossings)
        └─▶ SignificantEventEngine (deduplicated IntelligenceEvents)
        ▼
SessionSnapshot (snapshot_dict) — Phase-3 delivery foundation
```

**Provider independence contract**: `app.analysis` imports nothing from
`app.providers` (pinned by test). Input = canonical envelope payloads only.

## 2. Determinism & ordering

- Identical input stream ⇒ identical events + snapshot (verified: two full
  runs of session 11353 produce byte-identical summaries vs
  `tests/fixtures/backtest_baseline_11353.json`).
- **Context-primed deferral**: Lap/SectorTime envelopes are buffered until the
  first TyreStint/PitStop primer (bounded at 20k), because providers may
  deliver stint context late (verified: first stint record of the real race
  recording arrived at event 136,815). Buffer-full flushes and proceeds
  unprimed — data is never dropped.
- **Retroactive stint assignment**: laps land in a per-driver ledger; when a
  stint record arrives, laps inside [lap_start, lap_end] are (re)assigned to
  it. Final state converges deterministically; early snapshots honestly show
  unknown compounds until records arrive.

## 3. Incremental design

Every analyzer keeps O(drivers×pairs) state and updates on each event; there
is no per-update session recompute. Rolling windows use bounded deques/lists;
the lap ledger is one small dict per driver. Memory for a full race session
(1.07M events): **~99 MB peak** including ingest pipeline overhead.

## 4. Benchmarks (recorded, Windows workstation, single process)

Full 2026 Dutch GP replay through ingest + analysis:

| Metric | Value |
|---|---|
| Events processed | 1,067,193 |
| Wall time | ~397 s |
| Throughput | **≈2,650 events/s** |
| Per-event latency p50 | **0.10 ms** |
| Per-event latency p95 | **0.31 ms** |
| Peak memory | 99.3 MB |

Live-session requirement (~200 msg/s peak from feeds) is covered with >10×
headroom. Re-benchmark after engine changes via
`scripts/backtest_analysis.py`.

## 5. Usage

```powershell
# live/backfill recording WITH analysis artifacts:
$env:F1_ANALYZE = "1"
python scripts\record_session.py --ref openf1:<key>
#  -> recordings/<name>/snapshot.json + intelligence_events.jsonl

# backtest/determinism/benchmark over any recording:
python scripts\backtest_analysis.py recordings\<name> `
    --baseline backend\tests\fixtures\backtest_baseline_11353.json [--update-baseline]
```

## 6. Module map

| File | Responsibility |
|---|---|
| `common/models.py` | DerivedProvenance, IntelligenceEvent, Severity/LapFlag/CleanAir, stats helpers |
| `common/dedup.py` | deterministic event keys + LRU deduper |
| `race_control.py` | phase projection + interference-period timeline |
| `laps.py` | ClassifiedLap + LapClassifier (rules in METRIC_DEFINITIONS §Lap) |
| `timing.py` | laps/PB/SB/positions/symbolic-gap handling |
| `sectors.py` | PB/SB/purple/green/yellow/theoretical/best-possible |
| `pace.py` | rolling N, stint avg, median, trend slope, clean-air v1 |
| `tyres.py` | lap ledger → stints → ESTIMATED degradation fit |
| `gaps.py` | pair sampling, closing rate s/lap, trend labels |
| `battles.py` | 7-state FSM with documented thresholds |
| `strategy.py` | pit-loss/window/undercut-overcut/rejoin primitives |
| `weather.py` | trailing-window OLS trends + threshold events |
| `session.py` | type→profile + meaningfulness matrix |
| `events.py` | SignificantEventEngine (emission + dedupe + severity) |
| `snapshot.py` | SessionSnapshot builder |

Normative metric texts: `METRIC_DEFINITIONS.md`, `PACE_METHODOLOGY.md`,
`TYRE_DEGRADATION.md`, `BATTLE_DETECTION.md`; event catalog:
`EVENT_DEFINITIONS.md`.
