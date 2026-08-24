# AI_CONTEXT_PACKS.md

Phase-5 builders remain the source; Phase 6 adds build_pack_from_engine()
which assembles the race_v1 pack from live engine state at job time:
leaderboard top10 facts, fastest lap, latest stint degradation per driver
(class D), active battles, strategy candidates w/ assumptions, weather,
race-control phase line. Bounded to 40 facts + 10 events.

Qualifying/practice packs reuse the Phase-5 builders when the profile matches.
Packs are validated (PackValidator) before dispatch and stored implicitly via
the audit trail in job records (question/pack-hash/response).
