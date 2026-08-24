# LIVE_LATENCY.md

Measured-only policy: latency numbers exist here only when a real live window
produced class-A samples. As of Phase 3 close, NO live F1 session has occurred
since ingestion went live (next round outside the window), therefore:

    source->ingestion p50/p95 : NOT YET MEASURED (machinery ready)
    end-to-end WS delivery    : measured locally - see SCALING.md ladder
                                (14.9 ms p50 @10 clients under max-speed replay)

Stage timers implemented for the next live window:
pipeline.process() wall time; AnalysisEngine per-event latency;
snapshot build / diff / ws broadcast percentiles (hub metrics).

Runbook: record during the live window with F1_ANALYZE=1, then
python scripts/live_latency_report.py <session_id>
Only observed values print; zero class-A samples => tool refuses a verdict.
