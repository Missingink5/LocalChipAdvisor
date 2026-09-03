"""Contract tests for the non-negotiable candidate partition rules."""

import pytest
from pydantic import ValidationError

from local_chip_advisor.domain import (
    CandidateBucket,
    CheckResult,
    CheckState,
    PublicationStatus,
    classify_candidate,
)


def check(state: CheckState, *, rule_id: str = "vin.range") -> CheckResult:
    evidence_ids = () if state is CheckState.UNKNOWN else ("ev:test:1",)
    return CheckResult(
        rule_id=rule_id,
        field_name=rule_id,
        state=state,
        requirement="confirmed test requirement",
        actual=None if state is CheckState.UNKNOWN else "test product value",
        reason="test-only deterministic result",
        evidence_ids=evidence_ids,
    )


def test_published_candidate_with_all_passes_is_formal() -> None:
    result = classify_candidate(
        product_id="TEST-MPS-001",
        publication_status=PublicationStatus.PUBLISHED,
        checks=(check(CheckState.PASS), check(CheckState.PASS, rule_id="iout.continuous")),
    )

    assert result.bucket is CandidateBucket.FORMAL


def test_any_failure_routes_candidate_to_near_match() -> None:
    result = classify_candidate(
        product_id="TEST-MPS-002",
        publication_status=PublicationStatus.PUBLISHED,
        checks=(check(CheckState.PASS), check(CheckState.FAIL, rule_id="vin.maximum")),
    )

    assert result.bucket is CandidateBucket.NEAR_MATCH


def test_unknown_routes_candidate_to_needs_verification() -> None:
    result = classify_candidate(
        product_id="TEST-MPS-003",
        publication_status=PublicationStatus.PUBLISHED,
        checks=(check(CheckState.PASS), check(CheckState.UNKNOWN, rule_id="thermal.ambient")),
    )

    assert result.bucket is CandidateBucket.NEEDS_VERIFICATION


def test_unreviewed_record_cannot_be_formal() -> None:
    result = classify_candidate(
        product_id="TEST-MPS-004",
        publication_status=PublicationStatus.DRAFT,
        checks=(check(CheckState.PASS),),
    )

    assert result.bucket is CandidateBucket.NEEDS_VERIFICATION


@pytest.mark.parametrize("state", [CheckState.PASS, CheckState.FAIL])
def test_decisive_check_without_evidence_is_rejected(state: CheckState) -> None:
    with pytest.raises(ValidationError, match="must bind at least one evidence_id"):
        CheckResult(
            rule_id="vin.range",
            field_name="vin.range",
            state=state,
            requirement="confirmed test requirement",
            actual="test product value",
            reason="test-only deterministic result",
        )


def test_empty_check_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one hard-constraint check"):
        classify_candidate(
            product_id="TEST-MPS-005",
            publication_status=PublicationStatus.PUBLISHED,
            checks=(),
        )
