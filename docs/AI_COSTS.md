# AI_COSTS.md

Cost controls implemented in the gateway/runtime:
- event-triggered commentary ONLY for CRITICAL/IMPORTANT severities or named
  critical types, with per-(type,drivers) 90 s cooldowns;
- bounded queue (20) drops excess requests rather than bursting spend;
- exact-question+fact-set response cache (cache_hits metric);
- token accounting per call (prompt/completion/total) aggregated in metrics;
- small-model default via env; expensive models are an operator choice;
- deterministic fallback means outages/budget exhaustion cost nothing.

Observed (mock provider): tokens 0 by definition. Real-provider budgeting:
multiply tokens by provider pricing; metrics expose everything needed.
Latency stage split: context build / model p50+p95 / validation / total -
reported separately from deterministic analysis latency by design.
