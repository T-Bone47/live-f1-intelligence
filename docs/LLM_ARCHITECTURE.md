# LLM_ARCHITECTURE.md

    LIVE DATA -> CANONICAL EVENTS -> DETERMINISTIC ANALYSIS
              -> ADVANCED INTELLIGENCE -> CONTEXT PACK -> LLM GATEWAY
              -> GROUNDED RESPONSE -> WEBSOCKET -> FRONTEND

## Placement

The AI layer lives in app/ai/* ONLY. app/analysis never imports it (contract-
tested). The gateway runs inside the SessionHub runtime as an attached AIRuntime:

- engine.sig listener -> trigger_from_event (cooldowns) -> bounded queue(20)
- worker builds the pack from live state, calls provider via LLMGateway,
  validates, broadcasts kind=ai frames through the normal sequenced fanout.

LLM latency can never block ingestion/analysis: jobs are asynchronous and the
deterministic pipeline has zero ai imports.

## Providers

build_provider() maps env config to adapters:
- mock (default): deterministic pack-based responder - no network/key; used by
  tests, dev dashboards and the evaluation harness.
- gemini: Google Gemini Developer API via REST (no SDK). Env:
  LLM_PROVIDER=gemini, LLM_MODEL=gemini-2.5-flash, GEMINI_API_KEY. Uses
  system_instruction + responseMimeType application/json; key sent via the
  x-goog-api-key header server-side; 429/503 map to ProviderTimeout so the
  standard fallback path engages.
- openai-compatible: plain httpx chat/completions against any compatible base
  URL/model - covers OpenAI, Azure, vLLM, Ollama AND OpenRouter
  (LLM_BASE_URL=https://openrouter.ai/api/v1).

Model routing is env-driven: LLM_PROVIDER / LLM_MODEL / LLM_BASE_URL /
LLM_API_KEY / GEMINI_API_KEY / LLM_AUTO_COMMENTARY.

Provider-failure semantics are uniform: every adapter maps transport/rate/
availability problems to ProviderTimeout and hard errors to ProviderError;
the gateway converts either into a deterministic fallback answer, so provider
outage can never take the dashboard down with it.
