"""Rules that place candidates into formal, near-match, or verification buckets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import (
    CandidateBucket,
    CandidateEvaluation,
    CheckResult,
    CheckState,
    EvidenceRef,
    LimitKind,
    PublicationStatus,
)


class EvidenceBindingError(ValueError):
    """Raised when a decisive result is not backed by valid current evidence."""


DECISIVE_LIMIT_KINDS = {
    LimitKind.RECOMMENDED_RANGE,
    LimitKind.GUARANTEED_MIN,
    LimitKind.GUARANTEED_MAX,
    LimitKind.RATED_MAX,
}


DEFAULT_REQUIRED_RULE_IDS = (
    "vin.range",
    "vout.range",
    "iout.continuous",
    "iout.peak",
    "surge.input",
    "thermal.ambient",
)


def classify_candidate(
    *,
    product_id: str,
    publication_status: PublicationStatus,
    checks: Iterable[CheckResult],
    required_rule_ids: Iterable[str] = DEFAULT_REQUIRED_RULE_IDS,
) -> CandidateEvaluation:
    """Classify a candidate without using model-generated judgment.

    Priority is deliberate: a known hard failure is shown as a near match even
    if another field is unknown. An unreviewed record can never be formal.
    """

    materialized_checks = tuple(checks)
    if not materialized_checks:
        raise ValueError("at least one hard-constraint check is required")

    states = {check.state for check in materialized_checks}

    required = frozenset(required_rule_ids)
    present_rule_ids = {check.rule_id for check in materialized_checks}
    missing_required_rule_ids = required - present_rule_ids

    if CheckState.FAIL in states:
        bucket = CandidateBucket.NEAR_MATCH
    elif (
        publication_status is not PublicationStatus.PUBLISHED
        or CheckState.UNKNOWN in states
        or missing_required_rule_ids
    ):
        bucket = CandidateBucket.NEEDS_VERIFICATION
    else:
        bucket = CandidateBucket.FORMAL

    return CandidateEvaluation(
        product_id=product_id,
        publication_status=publication_status,
        checks=materialized_checks,
        bucket=bucket,
    )


def validate_evidence_bindings(
    evaluation: CandidateEvaluation,
    evidence_by_id: Mapping[str, EvidenceRef],
    *,
    knowledge_base_version: str,
) -> None:
    """Ensure decisive checks resolve to reviewed evidence for this product and version."""

    for check in evaluation.checks:
        if check.state is CheckState.UNKNOWN:
            continue
        for evidence_id in check.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise EvidenceBindingError(f"unknown evidence_id: {evidence_id}")
            if evidence.product_id != evaluation.product_id:
                raise EvidenceBindingError(f"evidence belongs to another product: {evidence_id}")
            if evidence.field_name != check.field_name:
                raise EvidenceBindingError(f"evidence belongs to another field: {evidence_id}")
            if evidence.knowledge_base_version != knowledge_base_version:
                raise EvidenceBindingError(f"evidence belongs to another knowledge-base version: {evidence_id}")
            if not evidence.reviewed:
                raise EvidenceBindingError(f"evidence has not been reviewed: {evidence_id}")
            if evidence.limit_kind not in DECISIVE_LIMIT_KINDS:
                raise EvidenceBindingError(
                    f"{evidence.limit_kind} cannot prove a decisive hard constraint: {evidence_id}"
                )
