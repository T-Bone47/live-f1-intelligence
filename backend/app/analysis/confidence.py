"""Standardized confidence model (Phase 5).

CONFIDENCE_MODEL.md is normative. Confidence is computed from MEASURABLE
factors - never arbitrary:

    score = w_s*sample_score + w_c*completeness + w_f*fit_score
          + w_v*consistency_score + w_p*provider_reliability

    sample_score     = clamp(n / n_ref, 0, 1)
    completeness     = fraction of expected inputs actually present (0..1)
    fit_score        = r_squared if a model fit exists else neutral 0.5
    consistency_score= 1 - clamp(cv / cv_ref, 0, 1)   (cv = std/mean)
    provider_reliability = empirical 0..1 (defaults 0.9)

Weights: samples .30, completeness .25, fit .20, consistency .15, provider .10
Grade bands: >=0.75 HIGH, >=0.50 MEDIUM, >=0.25 LOW, else UNKNOWN-grade LOW.
No inputs at all -> UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.common.models import Confidence

WEIGHTS = {"samples": 0.30, "completeness": 0.25, "fit": 0.20,
           "consistency": 0.15, "provider": 0.10}
N_REFERENCE = 10
CV_REFERENCE = 0.05          # 5% coefficient of variation == perfectly consistent
DEFAULT_PROVIDER_RELIABILITY = 0.90


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class ConfidenceAssessment:
    grade: Confidence
    score: float
    factors: dict


def assess_confidence(
    *,
    samples: int = 0,
    completeness: float | None = None,
    fit_r2: float | None = None,
    cv: float | None = None,
    provider_reliability: float = DEFAULT_PROVIDER_RELIABILITY,
    missing_inputs: bool = False,
) -> ConfidenceAssessment:
    """Deterministic confidence assessment."""
    if missing_inputs or (samples == 0 and completeness in (None, 0.0)):
        return ConfidenceAssessment(grade=Confidence.NONE, score=0.0,
                                    factors={"reason": "no usable inputs"})

    sample_score = _clamp(samples / N_REFERENCE)
    comp = 1.0 if completeness is None else _clamp(completeness)
    fit = 0.5 if fit_r2 is None else _clamp(fit_r2)
    cons = 0.5 if cv is None else 1.0 - _clamp(cv / CV_REFERENCE)
    prov = _clamp(provider_reliability)

    score = (WEIGHTS["samples"] * sample_score
             + WEIGHTS["completeness"] * comp
             + WEIGHTS["fit"] * fit
             + WEIGHTS["consistency"] * cons
             + WEIGHTS["provider"] * prov)

    if score >= 0.75:
        grade = Confidence.HIGH
    elif score >= 0.50:
        grade = Confidence.MEDIUM
    elif score >= 0.25:
        grade = Confidence.LOW
    else:
        grade = Confidence.NONE

    return ConfidenceAssessment(
        grade=grade, score=round(score, 3),
        factors={"samples": samples, "sample_score": round(sample_score, 3),
                 "completeness": round(comp, 3), "fit_r2": fit_r2,
                 "consistency_score": round(cons, 3),
                 "provider_reliability": round(prov, 3)},
    )
