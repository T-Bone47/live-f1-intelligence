# CONFIDENCE_MODEL.md

score = 0.30*samples_score + 0.25*completeness + 0.20*fit_score +
        0.15*consistency_score + 0.10*provider_reliability

samples_score = min(n/10, 1); completeness = fraction of expected inputs
present; fit_score = r_squared (neutral 0.5 when no model fit);
consistency_score = 1 - min(cv/0.05, 1); provider_reliability defaults 0.90
until empirical per-provider stats exist.

Bands: >=0.75 HIGH, >=0.50 MEDIUM, >=0.25 LOW, below or NO INPUTS -> NONE.
Every consumer MUST surface the grade alongside the value. Grades are
computed, never hand-assigned.
