# RACE_PACE_2.md

Builds on PaceEngine representative laps. All outputs DERIVED, calc_version tracked.

| Metric | Formula | Inputs | Exclusions | Confidence inputs |
|---|---|---|---|---|
| clean_air_pace | mean(eligible laps where clean_air=TRUE) | PaceEngine laps + CleanAir v1 | non-TRUE laps | samples, completeness |
| traffic_adjusted_pace | mean(all) - observed_loss * traffic_fraction; loss = median(traffic laps) - mean(clean laps); requires >=3 each | gaps -> TrafficState per lap | UNKNOWN-traffic laps | samples, cv |
| tyre_adjusted_pace | mean(lap - rate*age) using stint ESTIMATED rates (age normalized to 0) | StintEngine fits | stints without fit | samples, fit fixed 0.5 prior |
| stint_normalized | per-stint tyre-adjusted means | same | same | per stint |
| team/driver/field pace | group means / median of medians | teams map from Driver envelopes | unclassified drivers | samples |

Events: PACE_GAIN/PACE_LOSS when rolling5 moves >=0.3 s between windows
(bucketed keys); PACE_CONVERGENCE/PACE_DIVERGENCE when field rolling5 spread
shifts >=0.15 s between half-windows.

LIMITATIONS: no fuel/track-evolution normalization yet; clean-air uses gap
thresholds (no DRS zones); negative ESTIMATED degradation can appear late-race
(fuel burn dominates) - documented, not corrected.
