"""Application-level orchestration for LocalChipAdvisor."""

from pathlib import Path

from local_chip_advisor.domain import RequirementCard
from local_chip_advisor.ranking import RankingPolicy
from local_chip_advisor.recommendation import (
    RecommendationResult,
    recommend_from_published_catalog,
)

from local_chip_advisor.requirements import (
    RequirementParser,
    RequirementReview,
    build_requirement_follow_up_questions,
    confirm_requirement_card,
    parse_requirement_follow_up,
    parse_requirement_request,
)


class LocalChipAdvisor:
    """Coordinate requirement parsing and deterministic review workflow."""

    def __init__(
        self,
        *,
        parser: RequirementParser,
    ) -> None:
        self._parser = parser

    def review_request(
        self,
        raw_request: str,
    ) -> tuple[RequirementReview, tuple[str, ...]]:
        """Parse an initial request and build deterministic follow-up questions."""

        review = parse_requirement_request(
            raw_request=raw_request,
            parser=self._parser,
        )
        questions = build_requirement_follow_up_questions(
            review,
        )

        return review, questions

    def review_follow_up(
        self,
        *,
        card: RequirementCard,
        raw_follow_up: str,
    ) -> tuple[RequirementReview, tuple[str, ...]]:
        """Parse a follow-up response and return the updated review and questions."""

        review = parse_requirement_follow_up(
            card=card,
            raw_follow_up=raw_follow_up,
            parser=self._parser,
        )
        questions = build_requirement_follow_up_questions(
            review,
        )

        return review, questions

    def confirm(
        self,
        card: RequirementCard,
    ) -> RequirementCard:
        """Explicitly confirm a complete requirement card."""

        return confirm_requirement_card(card)

    def recommend(
        self,
        *,
        database_path: str | Path,
        knowledge_base_version: str,
        requirements: RequirementCard,
        policy: RankingPolicy,
    ) -> RecommendationResult:
        """Delegate a confirmed requirement card to the deterministic pipeline."""

        return recommend_from_published_catalog(
            database_path=database_path,
            knowledge_base_version=knowledge_base_version,
            requirements=requirements,
            policy=policy,
        )
