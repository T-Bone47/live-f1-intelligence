"""Gemini provider tests (Phase 6.1): request shaping, parsing, error mapping,
build_provider routing, gateway integration. Real-API test runs only when
GEMINI_API_KEY is present in the environment."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.gateway import LLMGateway
from app.ai.prompts import parse_response
from app.ai.providers import (
    GeminiProvider,
    MockGroundedProvider,
    OpenAICompatibleProvider,
    build_provider,
)
from app.ai.validation import PackValidator, ResponseValidator


PACK = {
    "pack": "race_v1",
    "session_id": "openf1:x",
    "facts": [
        {"id": "deg1", "class": "D",
         "statement": "#1 stint 4 estimated degradation 0.02 s/lap",
         "values": {"rate": 0.02}, "confidence": "MEDIUM"},
        {"id": "lb1", "class": "C",
         "statement": "P1 #1 lap 40 best 74.321 rolling5 75.25 tyre HARD/24"},
    ],
}

GOOD_TEXT = json.dumps({
    "answer": "Degradation is estimated at 0.02 s/lap.",
    "severity": "INFO", "confidence": "MEDIUM",
    "evidence": ["deg1"], "insufficient_data": False,
})


class TestBuildProviderRouting:
    def test_gemini_route(self):
        p = build_provider("gemini", base_url=None,
                           api_key="k", model="gemini-2.5-flash")
        assert isinstance(p, GeminiProvider)
        assert p.model == "gemini-2.5-flash"

    def test_openrouter_is_openai_compatible(self):
        p = build_provider("openai-compatible",
                           base_url="https://openrouter.ai/api/v1",
                           api_key="k", model="x/y")
        assert isinstance(p, OpenAICompatibleProvider)

    def test_mock_still_works(self):
        assert isinstance(build_provider("mock", base_url=None, api_key=None,
                                         model="m"), MockGroundedProvider)

    def test_unknown_provider_rejected(self):
        with pytest.raises(ValueError):
            build_provider("hal9000", base_url=None, api_key=None, model="m")


class TestGeminiRequestShape:
    def _capture(self, status=200, body=None):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["json"] = json.loads(request.content.decode())
            return httpx.Response(status, json=body or {})

        return captured, handler

    def test_request_shaping_and_parsing(self):
        body = {
            "candidates": [{"content": {"parts":
                                        [{"text": GOOD_TEXT}]}}],
            "usageMetadata": {"promptTokenCount": 120,
                              "candidatesTokenCount": 40,
                              "totalTokenCount": 160},
        }
        captured, handler = self._capture(200, body)
        prov = GeminiProvider(api_key="secret", model="gemini-2.5-flash")
        prov._http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=10)

        import asyncio

        result = asyncio.run(prov.complete("SYS", '{"facts": []}', "q?"))
        asyncio.run(prov._http.aclose())

        assert "/models/gemini-2.5-flash:generateContent" in captured["url"]
        assert captured["headers"].get("x-goog-api-key") == "secret"
        b = captured["json"]
        assert b["system_instruction"]["parts"][0]["text"] == "SYS"
        assert b["generationConfig"]["responseMimeType"] == "application/json"
        assert "CONTEXT PACK" in b["contents"][0]["parts"][0]["text"]
        assert result.text == GOOD_TEXT
        assert result.usage["total"] == 160
        # key never leaks into the URL
        assert "secret" not in captured["url"]

    def test_rate_limit_maps_to_timeout(self):
        captured, handler = self._capture(429, {})
        prov = GeminiProvider(api_key="k", model="gemini-2.5-flash")
        prov._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        from app.ai.providers import ProviderTimeout

        import asyncio

        with pytest.raises(ProviderTimeout):
            asyncio.run(prov.complete("S", "{}", "q"))
        asyncio.run(prov._http.aclose())

    def test_hard_error_maps_to_provider_error(self):
        captured, handler = self._capture(400, {"error": {"message": "bad"}})
        prov = GeminiProvider(api_key="k", model="gemini-2.5-flash")
        prov._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        from app.ai.providers import ProviderError

        import asyncio

        with pytest.raises(ProviderError):
            asyncio.run(prov.complete("S", "{}", "q"))
        asyncio.run(prov._http.aclose())


class TestGatewayIntegration:
    async def _flow(self):
        class Scripted:
            name = "gemini"

            def __init__(self):
                self.calls = 0

            async def complete(self, system, context_json, question):
                self.calls += 1
                if self.calls == 1:
                    # hallucinated number -> must be rejected by validator
                    return type("R", (), {"text": json.dumps({
                        "answer": "Tyre deg is now 7.777 s/lap.",
                        "severity": "INFO", "confidence": "HIGH",
                        "evidence": ["deg1"], "insufficient_data": False}),
                        "model": "gemini-2.5-flash",
                        "usage": {"prompt": 10, "completion": 5, "total": 15}})()
                return type("R", (), {"text": GOOD_TEXT,
                                      "model": "gemini-2.5-flash",
                                      "usage": {}})()

        g = LLMGateway(Scripted())
        resp = await g.run_job(session_id="openf1:x", question="tyres?",
                               pack=PACK, mode="LIVE", snapshot_seq=1)
        return g, resp

    def test_hallucination_retry_then_grounding_pass(self):
        import asyncio

        g, resp = asyncio.run(self._flow())
        assert "0.02" in resp.answer
        assert [e.fact_id for e in resp.evidence] == ["deg1"]
        assert resp.model == "gemini-2.5-flash"
        assert g.metrics.retries == 1


class TestRealGeminiAPI:
    """Executed only when a real developer key is available (.env-driven);
    otherwise self-skips with an explicit message."""

    def _key_and_model(self) -> tuple[str, str]:
        import os

        from app.config import get_settings

        s = get_settings()
        key = os.environ.get("GEMINI_API_KEY") or s.gemini_api_key or ""
        model = os.environ.get("LLM_MODEL") or s.llm_model or \
            "gemini-flash-latest"
        return key, model

    def test_real_generate_content(self):
        import asyncio
        import json

        key, model = self._key_and_model()
        if not key or key == "your_key_here":
            self.skipTest("GEMINI_API_KEY not set - real-API validation skipped")
        prov = GeminiProvider(api_key=key, model=model)

        async def go():
            from app.ai.prompts import SYSTEM_PROMPT as _SYS

            prov2 = GeminiProvider(api_key=key, model=model)
            try:
                return await prov2.complete(_SYS, json.dumps(PACK),
                                            "How are the tyres behaving?")
            except Exception as exc:  # noqa: BLE001
                if "429" in str(exc):
                    pytest.skip("Gemini free-tier quota exhausted - rerun later")
                raise

        result = asyncio.run(go())
        parsed = parse_response(result.text)
        assert parsed["answer"]
        assert isinstance(parsed["evidence"], list)
