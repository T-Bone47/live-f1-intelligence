# AI_RESPONSE_CONTRACT.md

Wire shape (kind=ai frames and REST job responses):

{
  job_id, session_id, question,
  answer: str,
  severity: INFO|NOTABLE|IMPORTANT|CRITICAL,
  confidence: HIGH|MEDIUM|LOW,
  evidence: [{id, statement, values, confidence}],
  mode: LIVE|REPLAY,
  stale: bool,
  snapshot_seq: int,
  generated_at: iso,
  model: str,
  prompt_version: raceeng-1,
  insufficient_data: bool,
  changes?: [strings]        // when a change-pack accompanied the request
}

Frontend renders confidence chip, STALE badge, and clickable evidence chips
(title = fact statement). prompt_version travels with every response so
grounding behavior is auditable over time.
