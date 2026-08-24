# QUALIFYING_INTELLIGENCE.md

Phase tracking uses upstream qualifying_phase field when present (stored on
RCM rows); otherwise phase stays UNKNOWN.

- boundary_time(part_size=10): slowest time among top-10 bests.
- observe_boundary(): called on new field-best observations; emits
  QUALIFYING_CUTOFF_CHANGE when trailing slope >=0.02 s/observation.
- projected_cutoff: linear extrapolation one step ahead of trailing boundary
  history (needs >=3 points) with standard confidence.
- elimination_risk bands vs boundary: SAFE <=0.3 s, ELEVATED <=0.7, HIGH >0.7;
  no-time drivers UNKNOWN; every result labeled HYPOTHETICAL projection.
- theoretical_gain: actual_best - sum(best sectors).
- track_evolution: boundary slope direction (needs >=4 observations).
- driver_vs_field improvement subtracts field slope from driver slope -
  documented approximation.

Sector events (GAINING_IN_Sx etc.) emitted only when sector PB deltas exceed
noise thresholds across consecutive attempts.
