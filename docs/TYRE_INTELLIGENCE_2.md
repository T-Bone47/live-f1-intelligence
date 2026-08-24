# TYRE_INTELLIGENCE_2.md

model_version tyres-2.0. Model: a + b*age + c*age^2 (quadratic OLS; linear
(a,b) remains the headline estimate).

- warmup_laps: leading ages exceeding stint median by >0.3 s (needs n>=4).
- acceleration c reported at n>=8.
- thermal_cliff: DETECTED only if n>=10 AND c>=0.02 s/lap^2 AND last-quarter
  mean exceeds first-quarter mean by >=0.8 s; NOT_DETECTED otherwise;
  UNKNOWN when under-sampled - never claimed without evidence.
- confidence via CONFIDENCE_MODEL (samples + r2).

Outputs: estimated_degradation, base_pace, acceleration_s_per_lap2,
warmup_laps, thermal_cliff, sample_count, excluded_laps, r_squared,
confidence, model_version, limitations[]. Label: ESTIMATED DEGRADATION.

Backtest note: real Dutch GP final stints show small NEGATIVE b (fuel effect
dominates) - documented limitation, no fuel correction yet.
