"""Requirement review workflow before deterministic screening."""

from __future__ import annotations

from dataclasses import dataclass

from local_chip_advisor.domain import RequirementCard


@dataclass(frozen=True, slots=True)
class RequirementReview:
    """Review state for a normalized but not necessarily confirmed requirement card."""

    card: RequirementCard
    missing_fields: tuple[str, ...]
    ready_for_confirmation: bool


def build_requirement_review(
    card: RequirementCard,
) -> RequirementReview:
    """Report whether the normalized requirement card is complete enough to confirm."""

    missing_fields = card.missing_minimum_fields()

    return RequirementReview(
        card=card,
        missing_fields=missing_fields,
        ready_for_confirmation=(
            not missing_fields
            and not card.confirmed_by_user
        ),
    )


def confirm_requirement_card(
    card: RequirementCard,
) -> RequirementCard:
    """Confirm a complete requirement card for deterministic screening."""

    missing_fields = card.missing_minimum_fields()

    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ValueError(
            "cannot confirm incomplete requirement card: "
            f"{missing}"
        )

    return RequirementCard.model_validate(
        {
            **card.model_dump(),
            "confirmed_by_user": True,
        }
    )
