"""Phase 10.5 evidence layer: versioned, deterministic evidence contracts.

Live F1 Intelligence measures; consumers (RaceWise, the 10.6 UI) reason.
"""

from app.evidence.lap_comparison import (
    BUILDER_VERSION,
    EvidenceContractError,
    EvidenceInputError,
    SourceInfo,
    build_lap_comparison_evidence,
    parse_evidence,
    to_canonical_json,
    validate_request,
)
from app.evidence.schema import CONTRACT_VERSION, SUPPORTED_CONTRACTS, LapComparisonEvidenceV1

__all__ = [
    "BUILDER_VERSION",
    "CONTRACT_VERSION",
    "SUPPORTED_CONTRACTS",
    "EvidenceContractError",
    "EvidenceInputError",
    "LapComparisonEvidenceV1",
    "SourceInfo",
    "build_lap_comparison_evidence",
    "parse_evidence",
    "to_canonical_json",
    "validate_request",
]
