"""Stable recommendation result contract."""

from dataclasses import replace
from decimal import Decimal

from local_chip_advisor.ranking import (
    RankingCriterion,
    RankingPolicy,
)
from local_chip_advisor.recommendation import build_recommendation_result
from local_chip_advisor.screening import (
    CatalogScreeningResult,
    ScreenedCandidate,
)
from test_publication_gate import reviewed_evidence
from test_ranking import formal_candidate
from test_screening import confirmed_requirements


def formal_candidate_with_evidence(
    *,
    product_id: str,
    base_part_number: str,
    continuous_current_a: str,
) -> ScreenedCandidate:
    candidate = formal_candidate(
        product_id=product_id,
        base_part_number=base_part_number,
        continuous_current_a=continuous_current_a,
    )

    source = next(
        item
        for item in reviewed_evidence()
        if item.evidence_id == "ev:iout"
    )

    evidence = source.model_copy(
        update={
            "product_id": product_id,
        }
    )

    return replace(
        candidate,
        evidence=(evidence,),
    )


def test_recommendation_result_keeps_top3_and_key_evidence() -> None:
    candidates = (
        formal_candidate_with_evidence(
            product_id="MPS-3A",
            base_part_number="BUCK3A",
            continuous_current_a="3",
        ),
        formal_candidate_with_evidence(
            product_id="MPS-4A",
            base_part_number="BUCK4A",
            continuous_current_a="4",
        ),
        formal_candidate_with_evidence(
            product_id="MPS-5A",
            base_part_number="BUCK5A",
            continuous_current_a="5",
        ),
        formal_candidate_with_evidence(
            product_id="MPS-6A",
            base_part_number="BUCK6A",
            continuous_current_a="6",
        ),
    )

    screening_result = CatalogScreeningResult(
        formal=candidates,
        near_match=(),
        needs_verification=(),
    )

    result = build_recommendation_result(
        screening_result=screening_result,
        requirements=confirmed_requirements(),
        policy=RankingPolicy(
            criteria=(RankingCriterion.CURRENT_HEADROOM,),
        ),
    )

    assert tuple(
        item.rank
        for item in result.formal
    ) == (1, 2, 3)

    assert tuple(
        item.candidate.product_id
        for item in result.formal
    ) == (
        "MPS-6A",
        "MPS-5A",
        "MPS-4A",
    )

    assert tuple(
        item.ranking_criteria[0].value
        for item in result.formal
    ) == (
        Decimal("3.5"),
        Decimal("2.5"),
        Decimal("1.5"),
    )

    assert tuple(
        item.key_evidence[0].evidence_id
        for item in result.formal
    ) == (
        "ev:iout",
        "ev:iout",
        "ev:iout",
    )

    assert result.near_match == ()
    assert result.needs_verification == ()
