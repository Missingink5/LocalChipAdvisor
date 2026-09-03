"""Deterministic ranking contract for formal candidates."""

from decimal import Decimal

from local_chip_advisor.domain import (
    CandidateBucket,
    CandidateEvaluation,
    CheckResult,
    CheckState,
    PublicationStatus,
)
from local_chip_advisor.ranking import (
    RankingCriterion,
    RankingPolicy,
    rank_formal_candidates,
    rank_screening_result,
)
from local_chip_advisor.screening import (
    CatalogScreeningResult,
    ScreenedCandidate,
)
from test_publication_gate import publishable_draft
from test_screening import confirmed_requirements


def formal_candidate(
    *,
    product_id: str,
    base_part_number: str,
    continuous_current_a: str,
) -> ScreenedCandidate:
    product = publishable_draft().model_copy(
        update={
            "product_id": product_id,
            "base_part_number": base_part_number,
            "orderable_part_numbers": (base_part_number,),
            "publication_status": PublicationStatus.PUBLISHED,
            "iout_continuous_max_a": Decimal(continuous_current_a),
        }
    )

    evaluation = CandidateEvaluation(
        product_id=product_id,
        publication_status=PublicationStatus.PUBLISHED,
        checks=(
            CheckResult(
                rule_id="iout.continuous",
                field_name="iout.continuous",
                state=CheckState.PASS,
                requirement="continuous IOUT=2.5A",
                actual=f"{continuous_current_a}A continuous rated maximum",
                reason="test fixture",
                evidence_ids=("ev:iout",),
            ),
        ),
        bucket=CandidateBucket.FORMAL,
    )

    return ScreenedCandidate(
        product=product,
        evaluation=evaluation,
        evidence=(),
    )


def test_explicit_current_headroom_policy_ranks_formal_candidates() -> None:
    candidate_3a = formal_candidate(
        product_id="MPS-3A",
        base_part_number="BUCK3A",
        continuous_current_a="3",
    )

    candidate_5a = formal_candidate(
        product_id="MPS-5A",
        base_part_number="BUCK5A",
        continuous_current_a="5",
    )

    ranked = rank_formal_candidates(
        candidates=(candidate_3a, candidate_5a),
        required_continuous_current_a=Decimal("2.5"),
        policy=RankingPolicy(
            criteria=(RankingCriterion.CURRENT_HEADROOM,),
        ),
    )

    assert tuple(
        item.candidate.product_id
        for item in ranked
    ) == (
        "MPS-5A",
        "MPS-3A",
    )

    assert ranked[0].criteria[0].criterion is RankingCriterion.CURRENT_HEADROOM
    assert ranked[0].criteria[0].value == Decimal("2.5")
    assert ranked[1].criteria[0].value == Decimal("0.5")


def test_rank_screening_result_uses_confirmed_requirement_card() -> None:
    candidate_3a = formal_candidate(
        product_id="MPS-3A",
        base_part_number="BUCK3A",
        continuous_current_a="3",
    )

    candidate_5a = formal_candidate(
        product_id="MPS-5A",
        base_part_number="BUCK5A",
        continuous_current_a="5",
    )

    screening_result = CatalogScreeningResult(
        formal=(candidate_3a, candidate_5a),
        near_match=(),
        needs_verification=(),
    )

    ranked = rank_screening_result(
        screening_result=screening_result,
        requirements=confirmed_requirements(),
        policy=RankingPolicy(
            criteria=(RankingCriterion.CURRENT_HEADROOM,),
        ),
    )

    assert tuple(
        item.candidate.product_id
        for item in ranked
    ) == (
        "MPS-5A",
        "MPS-3A",
    )

    assert ranked[0].criteria[0].value == Decimal("2.5")
    assert ranked[1].criteria[0].value == Decimal("0.5")
