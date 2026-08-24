# PRACTICE_INTELLIGENCE.md

Run segmentation rules (per driver/stint):
- LIKELY_LONG_RUN: >=8 representative laps.
- LIKELY_SHORT_RUN: 2..4 laps.
- LIKELY_QUALI_SIM: cluster of >=2 laps within 3.5 s of session-best-relative
  pace window early in the run set.
- LIKELY_RACE_SIM: two consecutive halves whose means differ <1.0 s.

Outputs: long_run_average, short_run_average, consistency_cv (std/mean),
team_long_run aggregate over member drivers. Intent labels are ALWAYS
LIKELY_* - we cannot observe intent.
