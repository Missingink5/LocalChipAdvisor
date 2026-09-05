"""Requirement review workflow before deterministic screening."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from local_chip_advisor.domain import (
    RequirementCard,
    SurgeKnowledge,
)


class RequirementParser(Protocol):
    """Adapter contract for automated requirement extraction."""

    def parse(
        self,
        raw_request: str,
    ) -> "RequirementParsePayload":
        ...


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


def build_requirement_follow_up_questions(
    review: RequirementReview,
) -> tuple[str, ...]:
    """Build deterministic user questions for missing requirements."""

    questions: list[str] = []
    missing_fields = set(review.missing_fields)

    input_voltage_fields = {
        "vin_min_v",
        "vin_nominal_v",
        "vin_max_v",
    }
    if missing_fields & input_voltage_fields:
        questions.append(
            "请输入输入电压范围和标称值，例如：18到30V，标称24V。"
        )

    output_voltage_fields = {
        "vout_target_v",
        "vout_tolerance_percent",
    }
    if missing_fields & output_voltage_fields:
        questions.append(
            "请输入目标输出电压和允许误差，例如：5V，允许误差±2%。"
        )

    output_current_fields = {
        "iout_continuous_a",
        "iout_peak_a",
        "peak_duration_ms",
    }
    if missing_fields & output_current_fields:
        questions.append(
            "请输入持续输出电流、峰值电流和峰值持续时间，例如：持续2.5A，峰值3A持续10ms。"
        )

    thermal_fields = {
        "ambient_max_c",
        "thermal_conditions",
    }
    if missing_fields & thermal_fields:
        questions.append(
            "请输入最高环境温度和散热条件，例如：最高70°C，自然对流散热。"
        )

    surge_detail_fields = {
        "surge_voltage_v",
        "surge_duration_ms",
    }
    if missing_fields & surge_detail_fields:
        questions.append(
            "请输入输入浪涌电压和持续时间，例如：浪涌最高36V，持续2ms。"
        )

    if "surge_knowledge" in missing_fields:
        questions.append(
            "输入端浪涌情况是什么？请选择：存在浪涌、预计不存在额外浪涌、或目前未知。"
        )

    return tuple(questions)


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

    surge_knowledge: SurgeKnowledge | None = Field(
        default=None,
        description=(
            "Input surge status: PRESENT when surge or transient is explicitly present; "
            "NONE_EXPECTED when the user explicitly says no surge is expected; "
            "UNKNOWN when the user explicitly says surge status is unknown; "
            "null only when the user provides no surge information."
        ),
    )
    surge_voltage_v: Decimal | None = Field(default=None, gt=0)
    surge_duration_ms: Decimal | None = Field(default=None, gt=0)

    vout_target_v: Decimal | None = Field(default=None, gt=0)
    vout_tolerance_percent: Decimal | None = Field(default=None, gt=0)

    iout_continuous_a: Decimal | None = Field(default=None, gt=0)
    iout_peak_a: Decimal | None = Field(default=None, gt=0)
    peak_duration_ms: Decimal | None = Field(
        default=None,
        gt=0,
        description=(
            "Duration in milliseconds of the explicitly stated peak output current."
        ),
    )

    ambient_max_c: Decimal | None = Field(
        default=None,
        description=(
            "Maximum explicitly stated ambient operating temperature in degrees Celsius."
        ),
    )
    thermal_conditions: str | None = Field(
        default=None,
        description=(
            "Explicitly stated cooling or thermal condition, such as natural convection, "
            "forced airflow, heatsinking, or PCB thermal constraints."
        ),
    )


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


def parse_requirement_request(
    *,
    raw_request: str,
    parser: RequirementParser,
) -> RequirementReview:
    """Parse user text into an unconfirmed requirement review."""

    parsed = parser.parse(raw_request)

    card = build_unconfirmed_requirement_card(
        raw_request=raw_request,
        parsed=parsed,
    )

    return build_requirement_review(card)
