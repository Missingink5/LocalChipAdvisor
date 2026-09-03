"""Stable deterministic recommendation result assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from local_chip_advisor.domain import EvidenceRef, RequirementCard
from local_chip_advisor.ranking import (
    CriterionResult,
    RankingPolicy,
    rank_screening_result,
)
from local_chip_advisor.screening import (
    CatalogScreeningResult,
    ScreenedCandidate,
    screen_published_catalog,
)


@dataclass(frozen=True, slots=True)
class FormalRecommendation:
    """One ranked formal recommendation with program-bound evidence."""

    rank: int
    candidate: ScreenedCandidate
    ranking_criteria: tuple[CriterionResult, ...]
    key_evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    """Stable output before any natural-language explanation layer."""

    formal: tuple[FormalRecommendation, ...]
    near_match: tuple[ScreenedCandidate, ...]
    needs_verification: tuple[ScreenedCandidate, ...]


def _key_evidence(
    candidate: ScreenedCandidate,
) -> tuple[EvidenceRef, ...]:
    """Return reviewed evidence actually referenced by deterministic checks."""

    evidence_by_id = {
        item.evidence_id: item
        for item in candidate.evidence
    }

    ordered_ids: list[str] = []
    seen: set[str] = set()

    for check in candidate.evaluation.checks:
        for evidence_id in check.evidence_ids:
            if evidence_id in seen:
                continue

            if evidence_id not in evidence_by_id:
                raise ValueError(
                    f"candidate check references missing evidence: "
                    f"{candidate.product_id} / {evidence_id}"
                )

            seen.add(evidence_id)
            ordered_ids.append(evidence_id)

    return tuple(
        evidence_by_id[evidence_id]
        for evidence_id in ordered_ids
    )


def build_recommendation_result(
    *,
    screening_result: CatalogScreeningResult,
    requirements: RequirementCard,
    policy: RankingPolicy,
    formal_limit: int = 3,
) -> RecommendationResult:
    """Build ranked formal recommendations and preserve other buckets."""

    if formal_limit <= 0:
        raise ValueError("formal_limit must be greater than zero")

    ranked = rank_screening_result(
        screening_result=screening_result,
        requirements=requirements,
        policy=policy,
    )

    formal = tuple(
        FormalRecommendation(
            rank=index,
            candidate=item.candidate,
            ranking_criteria=item.criteria,
            key_evidence=_key_evidence(item.candidate),
        )
        for index, item in enumerate(
            ranked[:formal_limit],
            start=1,
        )
    )

    return RecommendationResult(
        formal=formal,
        near_match=screening_result.near_match,
        needs_verification=screening_result.needs_verification,
    )


def recommend_from_published_catalog(
    *,
    database_path: str | Path,
    knowledge_base_version: str,
    requirements: RequirementCard,
    policy: RankingPolicy,
    formal_limit: int = 3,
) -> RecommendationResult:
    """Run deterministic screening and recommendation assembly end to end."""

    screening_result = screen_published_catalog(
        database_path=database_path,
        knowledge_base_version=knowledge_base_version,
        requirements=requirements,
    )

    return build_recommendation_result(
        screening_result=screening_result,
        requirements=requirements,
        policy=policy,
        formal_limit=formal_limit,
    )
