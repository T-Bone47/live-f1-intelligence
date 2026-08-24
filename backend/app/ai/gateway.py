"""LLM Gateway (Phase 6): pack -> prompt -> provider -> validation -> response.

Pipeline per job:
    PackValidator (reject malformed context)
    -> provider.complete (retryable on timeout/5xx)
    -> parse_response
    -> ResponseValidator (grounding; retry ONCE with correction feedback)
    -> fallback deterministic answer if still failing

The gateway never blocks ingestion: it runs as awaited jobs from the AI queue.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from app.ai.models import (
    AIResponse,
    PROMPT_VERSION,
)
from app.ai.prompts import (
    CORRECTION_SUFFIX,
    SYSTEM_PROMPT,
    build_context_json,
    parse_response,
)
from app.ai.providers import ProviderAdapter
from app.ai.validation import (
    PackValidator,
    ResponseValidator,
    extract_evidence_from_response,
)

log = logging.getLogger(__name__)


@dataclass
class GatewayMetrics:
    requests: int = 0
    cache_hits: int = 0
    rejected: int = 0
    fallbacks: int = 0
    retries: int = 0
    provider_failures: int = 0
    context_build_ms: deque = field(default_factory=lambda: deque(maxlen=200))
    model_latency_ms: deque = field(default_factory=lambda: deque(maxlen=200))
    validate_ms: deque = field(default_factory=lambda: deque(maxlen=200))
    total_ms: deque = field(default_factory=lambda: deque(maxlen=200))
    tokens: dict = field(default_factory=lambda: {"prompt": 0, "completion": 0,
                                                  "total": 0})

    def as_dict(self) -> dict:
        def pct(dq, p):
            if not dq:
                return None
            s = sorted(dq)
            return round(s[min(len(s) - 1, int(len(s) * p))], 2)
        return {
            "requests": self.requests, "cache_hits": self.cache_hits,
            "rejected": self.rejected, "fallbacks": self.fallbacks,
            "retries": self.retries, "provider_failures": self.provider_failures,
            "context_build_p50_ms": pct(self.context_build_ms, 0.5),
            "model_latency_p50_ms": pct(self.model_latency_ms, 0.5),
            "model_latency_p95_ms": pct(self.model_latency_ms, 0.95),
            "validate_p50_ms": pct(self.validate_ms, 0.5),
            "total_p50_ms": pct(self.total_ms, 0.5),
            "tokens": dict(self.tokens),
        }


class LLMGateway:
    def __init__(self, provider: ProviderAdapter,
                 min_call_interval_s: float = 0.0,
                 cache_size: int = 500) -> None:
        self.provider = provider
        self.min_call_interval_s = float(min_call_interval_s)
        self._last_call: float | None = None
        self.metrics = GatewayMetrics()
        self._pack_validator = PackValidator()
        self._cache: dict[tuple, AIResponse] = {}
        self._cache_cap = cache_size
        self._cache_order: list[str] = []

    # ------------------------------------------------------------ helpers --

    @staticmethod
    def build_context_pack(pack: dict) -> str:
        t0 = time.perf_counter()
        ctx = build_context_json(pack)
        return ctx

    async def run_job(self, *, session_id: str, question: str,
                      pack: dict, mode: str, snapshot_seq: int,
                      current_seq: int | None = None,
                      job_id: str | None = None) -> AIResponse:
        job_id = job_id or str(uuid.uuid4())
        t_start = time.perf_counter()
        self.metrics.requests += 1

        # 1. validate pack
        pv = self._pack_validator.validate(pack)

        # 2. cache check (same question + same facts + same prompt contract)
        import hashlib

        key = hashlib.sha256(
            f"{question}|{sorted(pv.fact_ids)}|{session_id}|"
            f"{hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:16]}"
            .encode()).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            self.metrics.cache_hits += 1
            return cached

        # global rate limit: enforce minimum interval between provider calls
        # (protects free-tier quotas; 0 disables)
        if self.min_call_interval_s > 0 and self._last_call is not None:
            wait = self._last_call + self.min_call_interval_s - time.monotonic()
            if wait > 0:
                log.debug("rate limiter: %.1fs until next model call", wait)
                await asyncio.sleep(wait)
        self._last_call = time.monotonic()

        # 3. model call with ONE grounding retry
        attempt = 0
        correction_reason = ""
        while True:
            system = SYSTEM_PROMPT
            if attempt == 1:
                system = SYSTEM_PROMPT + CORRECTION_SUFFIX.format(
                    reason=correction_reason)
            ctx_json = build_context_json(pack)
            t_m = time.perf_counter()
            try:
                result = await self.provider.complete(system, ctx_json, question)
            except Exception as exc:  # noqa: BLE001 - mapped by providers
                self.metrics.provider_failures += 1
                return self.deterministic_fallback(
                    job_id=job_id, session_id=session_id, question=question,
                    pack=pack, mode=mode, snapshot_seq=snapshot_seq,
                    reason=f"provider {type(exc).__name__}")
            self.metrics.model_latency_ms.append((time.perf_counter() - t_m) * 1000)
            for k in ("prompt", "completion", "total"):
                self.metrics.tokens[k] += int(result.usage.get(k, 0))

            try:
                parsed = parse_response(result.text)
            except ValueError:
                if attempt == 0:
                    attempt += 1
                    correction_reason = "response was not valid JSON with an answer"
                    continue
                return self.deterministic_fallback(
                    job_id=job_id, session_id=session_id, question=question,
                    pack=pack, mode=mode, snapshot_seq=snapshot_seq,
                    reason="malformed model JSON")

            evidence = extract_evidence_from_response(parsed)

            # Grounding rule: factual claims require citations. An answer with
            # zero citations either dodged the pack or answered from memory -
            # both are ungrounded and must be corrected (or fallen back).
            if not evidence and not parsed.get("insufficient_data"):
                if attempt == 0:
                    attempt += 1
                    self.metrics.retries += 1
                    correction_reason = (
                        "answer cited no facts; every claim must reference "
                        "pack fact ids, or reply with the exact "
                        "insufficient-data JSON")
                    continue

            rv = ResponseValidator(pv)
            rv.load_statements(pack.get("facts", []))
            t_v = time.perf_counter()
            try:
                rv.validate(str(parsed["answer"]), evidence)
                self.metrics.validate_ms.append((time.perf_counter() - t_v) * 1000)
            except Exception as exc:  # noqa: BLE001 grounding failure
                if attempt == 0:
                    attempt += 1
                    self.metrics.retries += 1
                    correction_reason = str(exc)[:200]
                    continue
                self.metrics.rejected += 1

                # Grounding failed after retry. Per contract section 2, the
                # only safe published answer for an unanswerable-from-pack
                # question is the canonical insufficient-data response.
                return AIResponse(
                    job_id=job_id, session_id=session_id,
                    question=question,
                    answer="Insufficient data to determine this.",
                    severity="INFO", confidence="LOW", evidence=[],
                    mode=mode, snapshot_seq=snapshot_seq,
                    model=result.model, prompt_version=PROMPT_VERSION,
                    insufficient_data=True)

            stale = False
            if current_seq is not None and snapshot_seq and \
                    current_seq - snapshot_seq > 15:
                stale = True
            from app.ai.models import EvidenceRef

            statements = {f["id"]: f for f in pack.get("facts", [])}
            resp = AIResponse(
                job_id=job_id, session_id=session_id, question=question,
                answer=str(parsed["answer"]),
                severity=str(parsed.get("severity", "INFO")).upper(),
                confidence=str(parsed.get("confidence", "LOW")).upper(),
                evidence=[
                    EvidenceRef(
                        fact_id=eid,
                        statement=statements.get(eid, {}).get("statement", ""),
                        values=statements.get(eid, {}).get("values") or {},
                        confidence=statements.get(eid, {}).get("confidence"),
                    ) for eid in evidence],
                mode=mode, stale=stale, snapshot_seq=snapshot_seq,
                model=result.model, prompt_version=PROMPT_VERSION,
                insufficient_data=bool(parsed.get("insufficient_data")),
            )
            self._cache[key] = resp
            self._cache_order.append(key)
            if len(self._cache_order) > self._cache_cap:
                old = self._cache_order.pop(0)
                self._cache.pop(old, None)
            self.metrics.total_ms.append((time.perf_counter() - t_start) * 1000)
            return resp

    # ----------------------------------------------------------- fallback --

    def deterministic_fallback(self, *, job_id: str, session_id: str,
                               question: str, pack: dict, mode: str,
                               snapshot_seq: int, reason: str) -> AIResponse:
        self.metrics.fallbacks += 1
        facts = pack.get("facts", [])[:4]
        lines = [f"AI unavailable ({reason}). Deterministic summary:"]
        for f in facts:
            lines.append(f"- {f.get('statement', '')}")
        return AIResponse(
            job_id=job_id, session_id=session_id, question=question,
            answer="\n".join(lines), severity="INFO",
            confidence="MEDIUM" if facts else "LOW",
            evidence=[type("E", (), {"fact_id": f.get("id", ""),
                                     "statement": f.get("statement", ""),
                                     "values": f.get("values") or {},
                                     "confidence": None}) for f in facts],
            mode=mode, snapshot_seq=snapshot_seq, model="deterministic-fallback",
            prompt_version=PROMPT_VERSION)
