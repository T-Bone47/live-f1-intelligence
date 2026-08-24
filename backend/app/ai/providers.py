"""Provider abstraction (Phase 6).

Providers implement `complete(system, context, question) -> dict` returning
the parsed structured response. No SDK imports in core; OpenAI-compatible
providers use plain httpx. Keys stay server-side via env only.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    text: str                       # raw model text (expected JSON)
    model: str
    usage: dict                     # prompt/completion/total tokens when known


class ProviderError(RuntimeError):
    pass


class ProviderTimeout(ProviderError):
    pass


class ProviderAdapter(Protocol):
    name: str

    async def complete(self, system: str, context_json: str,
                       question: str) -> ProviderResult: ...

# ------------------------------------------------------------------ mock ----

class MockGroundedProvider:
    """Deterministic rule-based provider used for tests AND as the no-key dev
    default. It answers strictly from supplied fact statements - by
    construction it cannot hallucinate numbers outside the pack."""

    name = "mock"

    async def complete(self, system: str, context_json: str,
                       question: str) -> ProviderResult:
        pack = json.loads(context_json)
        facts = pack.get("facts", [])
        q = question.lower()
        picked: list[dict] = []
        matched = False
        keywords = {
            "tyre": {"kws": ("tyre", "degradation", "compound"),
                     "ids": ("deg",)},
            "pace": {"kws": ("pace", "faster", "speed", "quicker"),
                     "ids": ("lb",)},
            "battle": {"kws": ("battle", "closing", "overtake"),
                       "ids": ("battle",)},
            "strategy": {"kws": ("pit", "stop", "undercut", "strategy"),
                         "ids": ("strat",)},
            "traffic": {"kws": ("traffic",), "ids": ()},
            "weather": {"kws": ("rain", "weather", "wind"), "ids": ("weather",)},
        }
        for key, spec in keywords.items():
            if any(k in q for k in spec["kws"]):
                matched = True
                picked += [f for f in facts
                           if any(f.get("id", "").startswith(p)
                                  for p in spec["ids"])
                           or key in f.get("statement", "").lower()]
        generic = any(k in q for k in ("happening", "summar", "status"))
        if generic:
            picked = facts[:5]
            matched = True
        if not matched or not picked:
            out = {
                "answer": "Insufficient data to determine this.",
                "severity": "INFO",
                "confidence": "LOW",
                "evidence": [],
                "insufficient_data": True,
            }
            return ProviderResult(text=json.dumps(out), model=self.name,
                                  usage={"prompt": 0, "completion": 0,
                                         "total": 0})
        picked = picked[:5]
        ids = [f["id"] for f in picked]
        statements = " ".join(f.get("statement", "") for f in picked)
        answer = f"Based on current evidence: {statements.strip()[:400]}"
        out = {
            "answer": answer,
            "severity": "INFO",
            "confidence": "MEDIUM",
            "evidence": ids,
            "insufficient_data": False,
        }
        return ProviderResult(text=json.dumps(out), model=self.name,
                              usage={"prompt": len(system + context_json) // 4,
                                     "completion": len(answer) // 4,
                                     "total": 0})


# --------------------------------------------------- openai-compatible ------

class OpenAICompatibleProvider:
    """Works with OpenAI / Azure / vLLM / Ollama-style endpoints.

    Env: LLM_PROVIDER=openai-compatible, LLM_BASE_URL (default
    https://api.openai.com/v1), LLM_MODEL, LLM_API_KEY."""

    name = "openai-compatible"

    def __init__(self, *, base_url: str, api_key: str | None,
                 model: str, timeout_s: float = 30.0) -> None:
        import httpx  # local import: optional dependency path

        self._http = httpx.AsyncClient(timeout=timeout_s)
        self._base = base_url.rstrip("/")
        self._key = api_key
        self.model = model

    async def complete(self, system: str, context_json: str,
                       question: str) -> ProviderResult:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content":
                    f"CONTEXT PACK (JSON):\n{context_json}\n\nQUESTION:\n{question}"},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        try:
            resp = await self._http.post(f"{self._base}/chat/completions",
                                         json=body, headers=headers)
        except Exception as exc:  # noqa: BLE001
            raise ProviderTimeout(f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code == 408 or resp.status_code == 504:
            raise ProviderTimeout(f"provider timeout HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:160]}")
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"malformed provider response: {exc}") from exc
        return ProviderResult(text=text, model=self.model,
                              usage={"prompt": usage.get("prompt_tokens", 0),
                                     "completion": usage.get("completion_tokens", 0),
                                     "total": usage.get("total_tokens", 0)})


# ------------------------------------------------------------- gemini -------

GEMINI_DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    """Google Gemini Developer API (REST, no SDK).

    Env: LLM_PROVIDER=gemini, LLM_MODEL=gemini-2.5-flash, GEMINI_API_KEY=...
    Uses generateContent with system_instruction + JSON response mime type so
    answers parse through the same grounding validator as every other
    provider. Key is sent via the x-goog-api-key header (server-side only).
    """

    name = "gemini"

    def __init__(self, *, api_key: str | None, model: str,
                 base_url: str | None = None, timeout_s: float = 90.0) -> None:
        import httpx  # local import: optional dependency path

        self._http = httpx.AsyncClient(timeout=timeout_s)
        self._key = api_key or ""
        self._base = (base_url or GEMINI_DEFAULT_BASE).rstrip("/")
        self.model = model

    async def complete(self, system: str, context_json: str,
                       question: str) -> ProviderResult:
        url = f"{self._base}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self._key}
        user_text = f"CONTEXT PACK (JSON):\n{context_json}\n\nQUESTION:\n{question}"
        body: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        import asyncio

        attempts = 0
        backoff = 1.5
        while True:
            try:
                resp = await self._http.post(url, json=body, headers=headers)
            except Exception as exc:  # noqa: BLE001 - network layer
                raise ProviderTimeout(f"{type(exc).__name__}: {exc}") from exc
            if resp.status_code == 200:
                break
            transient = resp.status_code in (429, 500, 503)
            if transient and attempts < 3:
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if (retry_after or "").replace(
                    ".", "", 1).isdigit() else backoff
                log.warning("gemini transient %d - retry %d in %.1fs",
                            resp.status_code, attempts + 1, delay)
                attempts += 1
                backoff = min(backoff * 2, 8.0)
                await asyncio.sleep(delay)
                continue
            if transient:
                raise ProviderTimeout(
                    f"gemini rate/availability HTTP {resp.status_code} "
                    f"after {attempts + 1} attempts")
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:160]}")

        try:
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
            usage_meta = data.get("usageMetadata") or {}
            usage = {"prompt": usage_meta.get("promptTokenCount", 0),
                     "completion": usage_meta.get("candidatesTokenCount", 0),
                     "total": usage_meta.get("totalTokenCount", 0)}
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"malformed gemini response: {exc}") from exc
        return ProviderResult(text=text, model=self.model, usage=usage)


def build_provider(provider: str, *, base_url: str | None, api_key: str | None,
                   model: str) -> Any:
    if provider == "mock":
        return MockGroundedProvider()
    if provider == "gemini":
        return GeminiProvider(api_key=api_key, model=model,
                              base_url=base_url or GEMINI_DEFAULT_BASE)
    if provider == "openai-compatible":
        return OpenAICompatibleProvider(base_url=base_url or
                                        "https://api.openai.com/v1",
                                        api_key=api_key, model=model)
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}")
