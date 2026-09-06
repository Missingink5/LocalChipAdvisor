"""Domain types and deterministic decision rules."""

from .decision import EvidenceBindingError, classify_candidate, validate_evidence_bindings
from .models import (
    CandidateBucket,
    CandidateEvaluation,
    CheckResult,
    CheckState,
    EvidenceRef,
    LimitKind,
    PublicationStatus,
    RequirementCard,
    SurgeKnowledge,
    ThermalCoolingMode,
)
from .product import BuckProductRecord

__all__ = [
    "BuckProductRecord",
    "CandidateBucket",
    "CandidateEvaluation",
    "CheckResult",
    "CheckState",
    "EvidenceBindingError",
    "EvidenceRef",
    "LimitKind",
    "PublicationStatus",
    "RequirementCard",
    "SurgeKnowledge",
    "ThermalCoolingMode",
    "classify_candidate",
    "validate_evidence_bindings",
]
