"""Phase 6 AI layer tests: grounding, hallucination defense, retries,
fallback, stale protection, job queue. All provider-driven (no network)."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.ai.gateway import LLMGateway
from app.ai.jobs import AIRuntime
from app.ai.models import JobStatus
from app.ai.providers import (
    MockGroundedProvider,
    ProviderError,
    ProviderTimeout,
)
from app.ai.validation import (
    PackRejected,
    PackValidator,
    ResponseValidator,
    RetryableValidationError,
)

PACK = {
    "pack": "race_v1",
    "session_id": "openf1:x",
    "facts": [
        {"id": "lb1", "class": "C",
         "statement": "P1 #1 lap 40 best 74.321 rolling5 75.25 tyre HARD/24"},
        {"id": "deg1", "class": "D",
         "statement": "#1 stint 4 estimated degradation 0.02 s/lap",
         "values": {"rate": 0.02}, "confidence": "MEDIUM"},
        {"id": "battle3", "class": "C",
         "statement": "Battle #12 vs #1 ACTIVE_BATTLE last gap 0.45"},
    ],
}


class ScriptedProvider:
    """Returns queued responses in order; records prompts."""

    name = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    async def complete(self, system, context_json, question):
        self.prompts.append((system, context_json, question))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        from app.ai.providers import ProviderResult

        return ProviderResult(text=item, model="scripted", usage={})


def gateway(provider) -> LLMGateway:
    return LLMGateway(provider)


class TestPackValidation:
    def test_rejects_unknown_pack_name(self):
        with pytest.raises(PackRejected):
            PackValidator().validate({"pack": "chat_v9", "facts": []})

    def test_rejects_duplicate_fact_ids(self):
        bad = {**PACK, "facts": [PACK["facts"][0], PACK["facts"][0]]}
        with pytest.raises(PackRejected, match="duplicate"):
            PackValidator().validate(bad)

    def test_rejects_missing_statement(self):
        bad = {"pack": "race_v1", "session_id": "s",
               "facts": [{"id": "x", "class": "A"}]}
        with pytest.raises(PackRejected):
            PackValidator().validate(bad)

    def test_valid_pack_passes_with_numeric_universe(self):
        r = PackValidator().validate(PACK)
        assert "deg1" in r.fact_ids
        assert 0.02 in r.numeric_universe["deg1"]


class TestGroundedAnswers:
    def _run(self, response_text, question="How are tyres behaving?"):
        g = gateway(ScriptedProvider([response_text]))
        return asyncio_run(g.run_job(session_id="openf1:x", question=question,
                                     pack=PACK, mode="LIVE", snapshot_seq=10))

    def test_mock_provider_grounded_answer(self):
        resp = asyncio_run(gateway(MockGroundedProvider()).run_job(
            session_id="openf1:x", question="How are tyres behaving?",
            pack=PACK, mode="LIVE", snapshot_seq=5))
        assert "Insufficient data" not in resp.answer
        ids = [e.fact_id for e in resp.evidence]
        assert ids and all(i in {f["id"] for f in PACK["facts"]} for i in ids)
        assert resp.model == "mock"

    def test_insufficient_data_path(self):
        empty_pack = {"pack": "race_v1", "session_id": "openf1:x",
                      "facts": [{"id": "none1", "class": "C",
                                 "statement": "no data yet"}]}
        resp = asyncio_run(gateway(MockGroundedProvider()).run_job(
            session_id="openf1:x", question="Why is Norris faster?",
            pack=empty_pack, mode="LIVE", snapshot_seq=1))
        assert resp.insufficient_data is True


def asyncio_run(coro):
    return asyncio.run(coro)


class TestHallucinationDefense:
    def _validator(self):
        pv = PackValidator().validate(PACK)
        rv = ResponseValidator(pv)
        rv.load_statements(PACK["facts"])
        return rv

    def test_hallucinated_float_rejected_retryable(self):
        rv = self._validator()
        with pytest.raises(RetryableValidationError, match="not supported"):
            rv.validate("Degradation is now 3.7 s/lap.", ["deg1"])

    def test_supported_number_passes(self):
        rv = self._validator()
        rv.validate("Estimated degradation around 0.02 s/lap.", ["deg1"])

    def test_derived_difference_allowed(self):
        rv = self._validator()
        # gap difference between two cited numbers
        rv.validate("The gap moved by roughly 0.43 seconds.", ["battle3", "deg1"])

    def test_unsupported_driver_token_rejected(self):
        rv = self._validator()
        with pytest.raises(RetryableValidationError, match="#77"):
            rv.validate("Driver #77 is struggling.", ["lb1"])

    def test_supported_driver_token_ok(self):
        rv = self._validator()
        rv.validate("Driver #1 manages the stint well.", ["deg1"])


class TestRetryAndFallback:
    def test_retry_once_then_success(self):
        good = json.dumps({"answer": "Degradation ~0.02 s/lap.",
                           "severity": "INFO", "confidence": "MEDIUM",
                           "evidence": ["deg1"], "insufficient_data": False})
        bad = json.dumps({"answer": "Verstappen will pit in 3 laps for 99.9 "
                                    "softs on lap 55.",
                          "severity": "INFO", "confidence": "HIGH",
                          "evidence": ["deg1"], "insufficient_data": False})
        prov = ScriptedProvider([bad, good])
        g = gateway(prov)
        resp = asyncio_run(g.run_job(session_id="openf1:x", question="tyres?",
                                     pack=PACK, mode="LIVE", snapshot_seq=1))
        assert "0.02" in resp.answer
        assert g.metrics.retries == 1

    def test_fallback_after_two_failures(self):
        bad = json.dumps({"answer": "Invented 123456.78 number.",
                          "evidence": ["deg1"], "severity": "INFO",
                          "confidence": "HIGH", "insufficient_data": False})
        prov = ScriptedProvider([bad, bad])
        g = gateway(prov)
        resp = asyncio_run(g.run_job(session_id="openf1:x", question="q",
                                     pack=PACK, mode="LIVE", snapshot_seq=1))
        # grounding-rejection returns canonical insufficient response
        assert resp.insufficient_data is True
        assert "Insufficient data to determine this." in resp.answer
        assert g.metrics.rejected == 1

    def test_provider_timeout_maps_to_fallback(self):
        prov = ScriptedProvider([ProviderTimeout("t/o")])
        g = gateway(prov)
        resp = asyncio_run(g.run_job(session_id="openf1:x", question="q",
                                     pack=PACK, mode="LIVE", snapshot_seq=1))
        assert resp.model == "deterministic-fallback"
        assert g.metrics.provider_failures == 1

    def test_malformed_json_retries_then_fallbacks(self):
        prov = ScriptedProvider(["not json at all", "still not json"])
        g = gateway(prov)
        resp = asyncio_run(g.run_job(session_id="openf1:x", question="q",
                                     pack=PACK, mode="LIVE", snapshot_seq=1))
        assert resp.model == "deterministic-fallback"

    def test_provider_hard_error_returns_fallback(self):
        """Provider failure never raises to callers: gateway degrades to the
        deterministic fallback (spec section 20)."""
        prov = ScriptedProvider([ProviderError("HTTP 500")])
        g = gateway(prov)
        resp = asyncio_run(g.run_job(session_id="openf1:x", question="q",
                                     pack=PACK, mode="LIVE", snapshot_seq=1))
        assert resp.model == "deterministic-fallback"
        assert g.metrics.provider_failures == 1


class TestStaleProtection:
    def test_stale_marked_when_session_moved(self):
        good = json.dumps({"answer": "Degradation ~0.02 s/lap.",
                           "evidence": ["deg1"], "severity": "INFO",
                           "confidence": "MEDIUM", "insufficient_data": False})
        g = gateway(ScriptedProvider([good]))
        resp = asyncio_run(g.run_job(session_id="openf1:x", question="q",
                                     pack=PACK, mode="LIVE",
                                     snapshot_seq=100, current_seq=140))
        assert resp.stale is True

    def test_fresh_response_not_stale(self):
        good = json.dumps({"answer": "ok.", "evidence": [],
                           "severity": "INFO", "confidence": "LOW",
                           "insufficient_data": False})
        g = gateway(ScriptedProvider([good]))
        resp = asyncio_run(g.run_job(session_id="openf1:x", question="q",
                                     pack=PACK, mode="LIVE",
                                     snapshot_seq=100, current_seq=105))
        assert resp.stale is False


class TestJobQueue:
    async def _runtime_flow(self):
        runtime = AIRuntime(gateway(MockGroundedProvider()))
        received: list[dict] = []
        engine = type("E", (), {})()
        engine.session_id = "openf1:x"
        engine.ctx = type("P", (), {"profile": None})()
        engine.flush_deferred = lambda: None
        engine.snapshot_dict = lambda: {
            "session_id": "openf1:x", "leaderboard":
                [{"position": 1, "driver_number": 1, "lap_number": 3,
                  "personal_best_s": 74.3, "rolling5_s": 75.0,
                  "compound": "HARD", "tyre_age": 12}],
            "fastest_lap": None, "active_battles": [], "weather": {},
            "recent_events": []}
        engine.intelligence = lambda: {"tyres_2": {}, "strategy_candidates": None}
        engine.sig = type("S", (), {"listeners": []})()
        runtime.attach(engine, broadcast=received.append,
                       get_current_seq=lambda: 5)
        await runtime.start_worker()
        job_id = runtime.ask("openf1:x", "What is happening?", snapshot_seq=3)
        for _ in range(50):
            await asyncio.sleep(0.05)
            if runtime.jobs[job_id].status in (JobStatus.DONE, JobStatus.FALLBACK):
                break
        await runtime.stop()
        return runtime, job_id, received

    def test_user_question_completes_and_broadcasts(self):
        import asyncio as aio

        runtime, job_id, received = aio_run(self._runtime_flow())
        job = runtime.jobs[job_id]
        assert job.status.value in ("DONE", "FALLBACK")
        assert any(f.get("kind") == "ai" for f in received)

    def test_cooldown_blocks_repeat_auto_trigger(self):
        runtime = AIRuntime(gateway(MockGroundedProvider()))
        from app.analysis.common.models import IntelligenceEvent, Severity, DerivedProvenance
        from datetime import datetime, timezone

        ev = IntelligenceEvent(
            event_key="k", event_type="OVERTAKE", session_id="s",
            timestamp=datetime.now(timezone.utc), driver_numbers=(1, 2),
            severity=Severity.IMPORTANT,
            provenance=DerivedProvenance(session_id="s",
                                         calculated_at=datetime.now(timezone.utc)))
        first = runtime.trigger_from_event(ev)
        second = runtime.trigger_from_event(ev)
        assert first is not None and second is None   # cooldown

    def test_queue_full_raises(self):
        runtime = AIRuntime(gateway(MockGroundedProvider()))
        runtime.queue._max_size = runtime.queue.maxsize  # noqa: SLF001
        while not runtime.queue.full():
            runtime.enqueue(kind="user", question="fill")
        from app.ai.models import AIJobQueueFull

        with pytest.raises(AIJobQueueFull):
            runtime.ask("s", "one more", snapshot_seq=0)


def aio_run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


class TestAnalysisIndependence:
    def test_analysis_never_imports_ai_or_providers(self):
        import app.analysis as pkg
        import inspect

        src = inspect.getsource(pkg)
        for banned in ("app.ai", "providers.Mock", "llm", "LLMGateway"):
            assert banned.lower() not in src.lower() or banned == "llm" and \
                "llm" not in src.lower()
