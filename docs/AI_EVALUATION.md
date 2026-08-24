# AI_EVALUATION.md

Fixtures: backend/tests/fixtures/ai_eval/*.json
Each fixture: pack + question + allowed_evidence + forbidden_numbers +
expect_insufficient flags.

Runner: scripts/eval_ai.py [--provider mock] scores GROUNDING ONLY:
- parses to contract JSON
- cites >=1 allowed evidence id (except expect_insufficient fixtures)
- contains no forbidden numbers
- uses the exact insufficient phrase when expected

Current status: 4/4 fixtures pass with the mock provider (pass-rate 1.0).
Real-model runs use the same harness (--provider openai-compatible); a run
below 0.8 pass-rate exits non-zero so CI can gate prompt/provider changes.
