"""Stable recommendation result contract."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from test_publication_gate import publishable_draft, reviewed_evidence
from test_ranking import formal_candidate
from test_screening import confirmed_requirements

from local_chip_advisor.catalog.publication import prepare_published_product
from local_chip_advisor.catalog.sqlite_store import save_published_catalog
from local_chip_advisor.ranking import (
    RankingCriterion,
    RankingPolicy,
)
from local_chip_advisor.recommendation import (
    build_recommendation_result,
    candidate_issues,
    recommend_from_published_catalog,
)
from local_chip_advisor.screening import (
    CatalogScreeningResult,
    ScreenedCandidate,
)


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


def test_recommend_from_published_catalog_runs_end_to_end(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog.sqlite3"

    evidence = reviewed_evidence()

    product = prepare_published_product(
        product=publishable_draft(),
        evidence=evidence,
    )

    save_published_catalog(
        database_path=database_path,
        product=product,
        evidence=evidence,
    )

    result = recommend_from_published_catalog(
        database_path=database_path,
        knowledge_base_version="kb-dev-v1",
        requirements=confirmed_requirements(),
        policy=RankingPolicy(
            criteria=(RankingCriterion.CURRENT_HEADROOM,),
        ),
    )

    # MP4570 has no explicit reviewed ambient operating rating,
    # so it must not become a formal recommendation.
    assert result.formal == ()
    assert result.near_match == ()

    assert tuple(
        item.product_id
        for item in result.needs_verification
    ) == (
        "MPS-MP4570",
    )


def test_candidate_issues_exposes_unknown_verification_reason(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog.sqlite3"

    evidence = reviewed_evidence()

    product = prepare_published_product(
        product=publishable_draft(),
        evidence=evidence,
    )

    save_published_catalog(
        database_path=database_path,
        product=product,
        evidence=evidence,
    )

    result = recommend_from_published_catalog(
        database_path=database_path,
        knowledge_base_version="kb-dev-v1",
        requirements=confirmed_requirements(),
        policy=RankingPolicy(
            criteria=(RankingCriterion.CURRENT_HEADROOM,),
        ),
    )

    candidate = result.needs_verification[0]
    issues = candidate_issues(candidate)

    # Every UNKNOWN rule must surface: current applicability and total-error
    # capability are not fully structured, the peak fallback has no stated
    # rating regime, and no explicit ambient operating rating is available.
    issues_by_rule = {
        issue.rule_id: issue
        for issue in issues
    }

    assert set(issues_by_rule) == {
        "vout.tolerance",
        "iout.continuous",
        "iout.peak",
        "thermal.ambient",
    }

    tolerance_issue = issues_by_rule["vout.tolerance"]

    assert tolerance_issue.state.value == "UNKNOWN"
    assert tolerance_issue.requirement.startswith(
        "output-voltage tolerance within ±2%"
    )
    assert tolerance_issue.actual is None
    assert "no structured total output-voltage error" in tolerance_issue.reason
    assert tolerance_issue.evidence == ()

    peak_issue = issues_by_rule["iout.peak"]

    assert peak_issue.state.value == "UNKNOWN"
    assert "cooling regime" in peak_issue.reason
    assert peak_issue.evidence == ()

    issue = issues_by_rule["thermal.ambient"]

    assert issue.rule_id == "thermal.ambient"
    assert issue.state.value == "UNKNOWN"
    assert issue.requirement.startswith("ambient maximum=70")
    assert issue.actual is None
    assert "junction-temperature limits alone" in issue.reason
    assert issue.evidence == ()


def test_recommendation_result_embeds_issues_for_verification_candidate(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog.sqlite3"

    evidence = reviewed_evidence()

    product = prepare_published_product(
        product=publishable_draft(),
        evidence=evidence,
    )

    save_published_catalog(
        database_path=database_path,
        product=product,
        evidence=evidence,
    )

    result = recommend_from_published_catalog(
        database_path=database_path,
        knowledge_base_version="kb-dev-v1",
        requirements=confirmed_requirements(),
        policy=RankingPolicy(
            criteria=(RankingCriterion.CURRENT_HEADROOM,),
        ),
    )

    item = result.needs_verification[0]

    assert item.candidate.product_id == "MPS-MP4570"

    issues_by_rule = {
        issue.rule_id: issue
        for issue in item.issues
    }

    assert set(issues_by_rule) == {
        "vout.tolerance",
        "iout.continuous",
        "iout.peak",
        "thermal.ambient",
    }
    assert issues_by_rule["vout.tolerance"].state.value == "UNKNOWN"
    assert issues_by_rule["iout.continuous"].state.value == "UNKNOWN"
    assert issues_by_rule["iout.peak"].state.value == "UNKNOWN"
    assert issues_by_rule["thermal.ambient"].state.value == "UNKNOWN"
