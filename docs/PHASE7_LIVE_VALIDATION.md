# PHASE7_LIVE_VALIDATION.md

| | |
|---|---|
| Status | **WAITING_FOR_LIVE_SESSION** |
| As of | 2026-08-24 |
| Next live window | R13 Italian GP — FP ~2026-09-04, Race 2026-09-06 13:00 UTC |

---

## 1. Empirical status (measured, not assumed)

| Check | Result | Evidence |
|---|---|---|
| OpenF1 latest session | 11353 Dutch GP Race, ended 2026-08-23T15:00Z (**21.6 h ago**) | `sessions?session_key=latest` |
| Within live window now | NO | window math in harness exit path |
| Next F1 window | R13 Italian GP — sessions from 2026-09-04 | Jolpica schedule probe |
| SignalR feed frames right now | NONE in 20 s subscribe window (9 channels snapshotted) | `probe_signalr.py --subscribe` |
| SignalR snapshot structure captured | TimingData.Lines keyed by driver number w/ GapToLeader / IntervalToPositionAhead{Value,Catching} / Line / Position — real protocol evidence for Phase-8+ parsing | same probe |

Per rule 23 the live acceptance is **deferred**, not failed.

## 2. One-command runbook (when a session goes live)

```powershell
# T-30 min before session start
python scripts\live_acceptance.py --duration 7200
```

The harness automatically:
1. Detects the live session (exits code 3 with WAITING_FOR_LIVE_SESSION otherwise).
2. Connects OpenF1; records raw + canonical frames (Recorder).
3. Runs analysis + intelligence; serves WS; measures stage latencies.
4. Triggers grounded Gemini commentary on critical events (cooldowns active).
5. Writes `artifacts/live-<key>/`: acceptance.json (per-channel latency
   p50/p95/p99), snapshot.json, intelligence.json, ai_events.jsonl,
   quality.json.
6. Security-scans for key leakage every run.

Then:
```powershell
python scripts\backtest_analysis.py recordings\live-<...>     # LIVE→REPLAY determinism
python scripts\eval_ai.py --provider gemini                    # grounding rate
python scripts\next_session_probe.py                           # window check
```

## 3. Pre-validated on this machine (REPLAY-labeled, not live)

| Item | Status |
|---|---|
| Full chain replay→analysis→hub→WS deltas | PASS (Phase 7 fix: cooperative yield in hub.feed — max-speed replay starved the loop) |
| REPLAY+Gemini chain (real event → pack → real model → kind=ai frame) | PASS (test_replay_gemini_chain.py, ~52 s incl. real calls) |
| Provider comparison semantics (MATCH/MISMATCH/MISSING_A/B) | PASS (8 tests) |
| Determinism baseline | PASS after Phase-5 event additions |
| Backend tests | 310 passed, 3 skipped |
| Frontend tests / build | 17 passed / clean strict-TS build |

Known quota note: free-tier Gemini per-minute limits exhaust under repeated
acceptance runs (429s observed). Mitigations shipped: gateway min-call
interval (`LLM_MIN_CALL_INTERVAL_S`, set to 12 in local .env), deterministic
fallback answers that are themselves grounded (pack facts only), and graceful
test skip/retry semantics. For the acceptance run, prefer a fresh-quota
window or paid tier.

## 4. Acceptance checklist mapping

Every §22 checkbox maps to a concrete artifact produced by
`live_acceptance.py` + the two follow-up commands above. The report template
(§24 fields 1–22) is filled by reading `artifacts/live-<key>/acceptance.json`
plus hub metrics printed during the run. None of it can be filled today —
and none of it will be invented.
