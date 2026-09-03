"""Evidence provenance must be complete before a decisive result can be rendered."""

import pytest

from local_chip_advisor.domain import (
    CandidateEvaluation,
    CheckResult,
    CheckState,
    EvidenceBindingError,
    EvidenceRef,
    LimitKind,
    PublicationStatus,
    classify_candidate,
    validate_evidence_bindings,
)


def check(state: CheckState) -> CheckResult:
    return CheckResult(
        rule_id="vin.range",
        field_name="vin.range",
        state=state,
        requirement="confirmed test requirement",
        actual="test product value",
        reason="test-only deterministic result",
        evidence_ids=("ev:test:1",),
    )


def evidence(**overrides: object) -> EvidenceRef:
    values: dict[str, object] = {
        "evidence_id": "ev:test:1",
        "product_id": "TEST-MPS-001",
        "field_name": "vin.range",
        "knowledge_base_version": "kb-test-v1",
        "document_id": "doc-test-v1",
        "sha256": "a" * 64,
        "document_title": "TEST DATASHEET - NOT A REAL PART",
        "document_version": "rev-test",
        "page": 1,
        "section": "Recommended Operating Conditions",
        "excerpt": "Test-only recommended input range.",
        "limit_kind": LimitKind.RECOMMENDED_RANGE,
        "test_conditions": "test fixture only",
        "source_url": "https://example.invalid/test-datasheet",
        "reviewed": True,
    }
    values.update(overrides)
    return EvidenceRef.model_validate(values)


def formal_evaluation() -> CandidateEvaluation:
    return classify_candidate(
        product_id="TEST-MPS-001",
        publication_status=PublicationStatus.PUBLISHED,
        checks=(check(CheckState.PASS),),
    )


def test_reviewed_current_evidence_binding_is_valid() -> None:
    validate_evidence_bindings(
        formal_evaluation(),
        {"ev:test:1": evidence()},
        knowledge_base_version="kb-test-v1",
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"product_id": "TEST-MPS-OTHER"}, "another product"),
        ({"field_name": "iout.continuous"}, "another field"),
        ({"knowledge_base_version": "kb-old"}, "another knowledge-base version"),
        ({"reviewed": False}, "has not been reviewed"),
        ({"limit_kind": LimitKind.TYPICAL}, "cannot prove"),
        ({"limit_kind": LimitKind.TYPICAL_CURVE}, "cannot prove"),
        ({"limit_kind": LimitKind.ABSOLUTE_MAXIMUM}, "cannot prove"),
    ],
)
def test_invalid_evidence_cannot_back_formal_result(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(EvidenceBindingError, match=message):
        validate_evidence_bindings(
            formal_evaluation(),
            {"ev:test:1": evidence(**overrides)},
            knowledge_base_version="kb-test-v1",
        )


def test_unknown_evidence_id_is_rejected() -> None:
    with pytest.raises(EvidenceBindingError, match="unknown evidence_id"):
        validate_evidence_bindings(
            formal_evaluation(),
            {},
            knowledge_base_version="kb-test-v1",
        )
