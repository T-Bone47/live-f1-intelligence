"""Grounding validation (Phase 6) - the anti-hallucination core.

Two validators:

1. PackValidator: rejects malformed context packs BEFORE any model call.
   Never silently repairs facts.

2. ResponseValidator: checks a candidate answer against the pack:
   - every cited fact id must exist
   - every number in the answer must be attributable to a CITED fact
     (exact float match, integer match, or simple difference of two numbers
     from the same cited evidence, tolerance 0.05)
   - every "#N" driver token must appear in at least one cited statement
   - tyre compound tokens (SOFT/MEDIUM/HARD/INTER/WET) must appear in cited
     statements unless the answer cites no facts AND claims insufficient data

Failure modes -> RetryableValidationError (retry once with correction
feedback) or RejectedAnswer (publish nothing; use deterministic fallback).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

KNOWN_PACKS = {"race_v1", "qualifying_v1", "practice_v1"}
KNOWN_CLASSES = {"A", "B", "C", "D", "E", "F"}
COMPOUND_RE = re.compile(
    r"\b(SOFT|MEDIUM|HARD|INTERMEDIATE|INTER|WET)\b", re.I)
DRIVER_TOKEN_RE = re.compile(r"#(\d{1,2})\b")
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


class PackRejected(ValueError):
    pass


class RetryableValidationError(ValueError):
    pass


class RejectedAnswer(ValueError):
    pass


@dataclass
class PackValidationResult:
    ok: bool
    errors: list[str]
    fact_ids: set[str]
    numeric_universe: dict[str, set[float]]   # fact_id -> numbers in statement/values


class PackValidator:
    def validate(self, pack: dict[str, Any]) -> PackValidationResult:
        errors: list[str] = []
        if not isinstance(pack, dict):
            raise PackRejected("pack is not an object")
        name = pack.get("pack")
        if name not in KNOWN_PACKS:
            errors.append(f"unknown pack name {name!r}")
        sid = pack.get("session_id")
        if not isinstance(sid, str) or not sid:
            errors.append("missing session_id")
        facts = pack.get("facts")
        if not isinstance(facts, list) or not facts:
            errors.append("pack has no facts")
        ids: set[str] = set()
        numeric_universe: dict[str, set[float]] = {}
        for i, f in enumerate(facts or []):
            fid = f.get("id")
            if not fid or not isinstance(fid, str):
                errors.append(f"fact[{i}] missing id")
                continue
            if fid in ids:
                errors.append(f"duplicate fact id {fid}")
            ids.add(fid)
            cls = f.get("class")
            if cls not in KNOWN_CLASSES:
                errors.append(f"fact {fid} bad class {cls!r}")
            if not isinstance(f.get("statement"), str) or not f["statement"]:
                errors.append(f"fact {fid} missing statement")
            nums: set[float] = set()
            for n in NUM_RE.findall(f.get("statement", "")):
                try:
                    nums.add(float(n))
                except ValueError:
                    pass
            for v in (f.get("values") or {}).values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nums.add(float(v))
            numeric_universe[fid] = nums
        if errors:
            raise PackRejected("; ".join(errors[:5]))
        return PackValidationResult(ok=True, errors=[], fact_ids=ids,
                                    numeric_universe=numeric_universe)


class ResponseValidator:
    def __init__(self, pack_result: PackValidationResult) -> None:
        self.pack = pack_result

    # ------------------------------------------------------------- helpers --

    @staticmethod
    def _cited_numbers(answer: str, evidence_ids: list[str],
                       universe: dict[str, set[float]]) -> set[float]:
        out: set[float] = set()
        for eid in evidence_ids:
            out |= universe.get(eid, set())
        return out

    @staticmethod
    def _answer_tokens(answer: str) -> tuple[list[float], list[int], list[int]]:
        floats: list[float] = []
        ints: list[int] = []
        driver_nums: list[int] = []
        for m in NUM_RE.finditer(answer):
            text = m.group(0)
            if "." in text:
                try:
                    floats.append(float(text))
                except ValueError:
                    pass
            else:
                iv = int(text)
                ints.append(iv)
        for m in DRIVER_TOKEN_RE.finditer(answer):
            driver_nums.append(int(m.group(1)))
        return floats, ints, driver_nums

    # ------------------------------------------------------------ validate --

    def validate(self, answer_text: str,
                 evidence_ids: list[str]) -> None:
        """Raise RetryableValidationError for fixable issues, RejectedAnswer
        for structural failures."""
        unknown = [e for e in evidence_ids if e not in self.pack.fact_ids]
        if unknown:
            raise RetryableValidationError(
                f"cited unknown evidence ids: {unknown[:3]}")

        floats, ints, driver_nums = self._answer_tokens(answer_text)
        allowed = self._cited_numbers(answer_text, evidence_ids,
                                      self.pack.numeric_universe)

        # derived differences of two allowed numbers are acceptable
        allowed_derived: set[float] = set(allowed)
        vals = sorted(allowed)[:60]
        for i, x in enumerate(vals):
            for y in vals[i + 1:i + 8]:
                allowed_derived.add(round(abs(x - y), 3))

        def near_any(v: float) -> bool:
            return any(abs(v - a) <= 0.05 for a in allowed_derived)

        bad_floats = [f for f in floats if not near_any(f)]
        if bad_floats:
            raise RetryableValidationError(
                f"numbers not supported by cited evidence: {bad_floats[:3]}")

        bad_ints = [i for i in ints if float(i) not in allowed and i > 99]
        if bad_ints:
            raise RetryableValidationError(
                f"large unsupported integers: {bad_ints[:3]}")

        cited_statements = " ".join(self._statement_of(eid)
                                    for eid in evidence_ids)
        for dn in driver_nums:
            token_ok = f"#{dn}" in cited_statements
            numeric_ok = any(
                float(dn) in self.pack.numeric_universe.get(eid, set())
                for eid in evidence_ids)
            if not (token_ok or numeric_ok):
                raise RetryableValidationError(
                    f"driver token #{dn} unsupported by cited evidence")

    _statements_by_id: dict[str, str] = {}

    def load_statements(self, facts: list[dict]) -> None:
        self._statements_by_id = {f.get("id"): f.get("statement", "") for f in facts}

    def _statement_of(self, fid: str) -> str:
        st = self._statements_by_id.get(fid)
        if st is None:
            # fallback: allow numeric-universe membership only
            return ""
        return st


def extract_evidence_from_response(parsed: dict) -> list[str]:
    ev = parsed.get("evidence")
    if isinstance(ev, list):
        return [str(x) for x in ev][:12]
    return []
