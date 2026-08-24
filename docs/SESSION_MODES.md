# SESSION_MODES.md (frontend supplement - Phase 4)

The Phase-0/0.5 mode profiles remain normative for ANALYSIS thresholds. This
addendum documents how the DASHBOARD consumes them.

profileFor() maps the backend session_type to one of PRACTICE / QUALIFYING /
SPRINT / RACE and toggles panel emphasis:

| Panel          | PRACTICE | QUALIFYING | SPRINT | RACE |
|----------------|----------|------------|--------|------|
| timing table   | yes      | yes        | yes    | yes  |
| sectors/theor. | high     | high       | normal | normal|
| pace/trend     | high     | normal     | high   | high |
| tyres/degrad.  | high     | low        | high   | high |
| battles        | hidden   | normal     | high   | high |
| strategy inputs| hidden   | hidden     | normal | high |

Replay mode reuses everything unchanged: same WS contract, same components;
only the mode badge and replay transport controls differ (pause/resume/speed
via POST /api/v1/replay/{id}/control). Quali part tracking/elimination
projection remains deferred to the analysis roadmap (backend first).
