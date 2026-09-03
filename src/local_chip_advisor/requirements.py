"""Requirement review workflow before deterministic screening."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from local_chip_advisor.domain import (
    RequirementCard,
    SurgeKnowledge,
)


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


class RequirementParsePayload(BaseModel):
    """Fields an automated parser may propose from the user's raw request."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    vin_min_v: Decimal | None = Field(default=None, gt=0)
    vin_nominal_v: Decimal | None = Field(default=None, gt=0)
    vin_max_v: Decimal | None = Field(default=None, gt=0)

    surge_knowledge: SurgeKnowledge | None = None
    surge_voltage_v: Decimal | None = Field(default=None, gt=0)
    surge_duration_ms: Decimal | None = Field(default=None, gt=0)

    vout_target_v: Decimal | None = Field(default=None, gt=0)
    vout_tolerance_percent: Decimal | None = Field(default=None, gt=0)

    iout_continuous_a: Decimal | None = Field(default=None, gt=0)
    iout_peak_a: Decimal | None = Field(default=None, gt=0)
    peak_duration_ms: Decimal | None = Field(default=None, gt=0)

    ambient_max_c: Decimal | None = None
    thermal_conditions: str | None = None


def build_unconfirmed_requirement_card(
    *,
    raw_request: str,
    parsed: RequirementParsePayload,
) -> RequirementCard:
    """Bind parser output to the user's exact text without granting confirmation."""

    return RequirementCard.model_validate(
        {
            "raw_request": raw_request,
            **parsed.model_dump(),
            "confirmed_by_user": False,
        }
    )


def parse_requirement_payload_json(
    response_text: str,
) -> RequirementParsePayload:
    """Validate one strict JSON parser response against the allowed schema."""

    return RequirementParsePayload.model_validate_json(
        response_text
    )
