# AI_ARCHITECTURE.md

| | |
|---|---|
| Status | Phase 0 |
| Prime directive | The LLM explains; it never measures. All numbers come from deterministic code. |

---

## 1. Pipeline (fixed order)

```
LIVE DATA → NORMALIZATION → DETERMINISTIC CALCULATIONS → EVENT DETECTION
          → CONTEXT BUILDING → LLM → VALIDATION/GROUNDING → EXPLANATION
```

The LLM sits at the END. It receives a bounded, precomputed **context pack**
and returns structured claims. Raw telemetry streams NEVER reach the model.

## 2. Context packs

A pack is a compact JSON document assembled by deterministic selectors:

```jsonc
{
  "pack_id": "uuid",
  "session": { "type":"RACE", "lap": 33, "status":"GREEN", "mode_profile":"RACE" },
  "trigger": { "event_ref": "...", "summary": "Undercut threat: Russell on Hamilton" },
  "facts": [                                  // each fact has stable id for citations
    { "id":"f1", "class":"C", "statement":"Russell rolling-5 pace: 92.41s vs Hamilton 92.87s",
      "values": { "rus_pace_s":92.41, "ham_pace_s":92.87 } },
    { "id":"f2", "class":"A", "statement":"Hamilton stint age 14 laps MEDIAN",
      "values": { "compound":"MEDIUM", "age_laps":14 } },
    { "id":"f3", "class":"D", "statement":"Projected crossover lap 36 ±2",
      "confidence": 0.6 }
  ],
  "budget_bytes": 8192,
  "instructions_key": "undercut_v1"           // prompt template ref, versioned
}
```

Rules:
- Selectors are per trigger-type (e.g., `undercut_v1` pulls: both drivers'
  rolling paces, tyre ages/compounds/degradation slopes, gap history, pit-loss
  estimate, track position). Packs are ≤ ~8 KB typical.
- Class-D facts must include `confidence`; class-E never appears inside a pack.
- Packs are stored (audit) — any AI statement must cite `fact.id`s.

## 3. Task catalog

| Task | Trigger | Output |
|---|---|---|
| Event explanation | priority ≤2 events (purple sector streak broken, undercut threat, SC deployment, big pace shift, lap deletion) | 2–4 sentence explanation + claims |
| Chat Q&A ("race engineer") | user question | grounded answer + optional chart refs |
| Periodic digest | every N laps / session end | narrative summary with metrics table |
| Strategy articulation | strategy events | pros/cons narration of computed scenarios (no new math) |
| Post-session report | FINISHED | full recap from stored canonical data |

## 4. Grounding contract (anti-hallucination)

Structured output schema enforced at generation time:

```jsonc
{ "headline": str,
  "body_markdown": str,
  "claims": [
    { "text": str,
      "evidence": ["f1","f2"],        // must exist in pack
      "kind": "observed|calculated|predicted|interpretation" }
  ],
  "uncertainty_notes": [str] }
```

Validator rejects responses whose claim evidence references missing facts or
whose numeric strings don't match pack values → auto-retry once with error
feedback, then degrade to template-generated text (deterministic) so the user
never sees unsupported numbers.

UI labeling rule: every AI element renders its claims' classes
(observed/calculated/predicted/interpretation) visibly.

## 5. Cost & rate controls

- Event-driven only; per-trigger cooldowns (same driver+type ≥90 s).
- Budgets: tokens/hour and calls/session configurable; soft budget → queue to
  post-session digest; hard budget → disable E-class until reset.
- Cache: identical (template, pack-hash) → cached answer (TTL short during live,
  permanent for historical/replay).
- Small fast model default; larger model opt-in for reports/digests.

## 6. Provider abstraction

```python
class LLMPort(Protocol):
    async def complete(self, *, system: str, messages: list[Message],
                       response_schema: type[BaseModel]) -> BaseModel: ...
```

Adapters: OpenAI-compatible HTTP (covers OpenAI/Azure/vLLM/Ollama/local),
config via env (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, keys). No vendor
SDK lock-in in core code.

## 7. What the AI must NEVER do

1. Invent telemetry or timing numbers (validator + citation enforcement).
2. Receive raw CarData/Position streams (architecturally impossible — builder
   only exposes aggregates).
3. Make strategy decisions presented as certainties (must label predicted +
   assumptions).
4. Override deterministic state (one-way data flow into LLM only).
5. Run during replay seek storms (debounced; digests recomputed on settle).

## 8. Evaluation

Golden-set of recorded sessions with hand-labeled expected insights per event;
CI job scores grounding-pass-rate, citation coverage, latency, cost. Regression
gate before prompt/template changes ship.
