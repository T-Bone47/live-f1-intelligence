"""AI layer data contracts (Phase 6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

PROMPT_VERSION = "raceeng-1"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    REJECTED = "REJECTED"      # failed grounding validation after retry
    FALLBACK = "FALLBACK"      # deterministic answer substituted
    STALE = "STALE"            # completed but session moved far ahead
    FAILED = "FAILED"          # provider error, no fallback possible


@dataclass(frozen=True)
class EvidenceRef:
    fact_id: str
    statement: str
    values: dict = field(default_factory=dict)
    confidence: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AIResponse:
    job_id: str
    session_id: str
    question: str
    answer: str
    severity: str                      # INFO|NOTABLE|IMPORTANT|CRITICAL
    confidence: str                    # HIGH|MEDIUM|LOW
    evidence: list[EvidenceRef]
    mode: str                          # LIVE|REPLAY
    stale: bool = False
    snapshot_seq: int = 0
    generated_at: str = field(default_factory=lambda: utcnow().isoformat())
    model: str = "mock-grounded-1"
    prompt_version: str = PROMPT_VERSION
    insufficient_data: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "question": self.question,
            "answer": self.answer,
            "severity": self.severity,
            "confidence": self.confidence,
            "evidence": [
                {"id": e.fact_id, "statement": e.statement,
                 "values": e.values, "confidence": e.confidence}
                for e in self.evidence
            ],
            "mode": self.mode,
            "stale": self.stale,
            "snapshot_seq": self.snapshot_seq,
            "generated_at": self.generated_at,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "insufficient_data": self.insufficient_data,
        }


@dataclass
class JobRecord:
    job_id: str
    session_id: str
    kind: str                       # auto:<event_type> | user
    question: str
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    snapshot_seq: int = 0
    response: AIResponse | None = None
    error: str | None = None
    timings_ms: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


class AIJobQueueFull(RuntimeError):
    pass
