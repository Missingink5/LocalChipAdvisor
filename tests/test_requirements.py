"""Requirement parsing and confirmation workflow contract."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from local_chip_advisor.domain import (
    RequirementCard,
    SurgeKnowledge,
)
from local_chip_advisor.requirements import (
    build_requirement_review,
    confirm_requirement_card,
    build_unconfirmed_requirement_card,
    RequirementParsePayload,
    parse_requirement_payload_json,
    parse_requirement_request,
)


def test_requirement_review_reports_missing_fields() -> None:
    card = RequirementCard(
        raw_request="24V bus to 5V, about 2A",
        vin_nominal_v=Decimal("24"),
        vout_target_v=Decimal("5"),
        iout_continuous_a=Decimal("2"),
        confirmed_by_user=False,
    )

    review = build_requirement_review(card)

    assert review.card is card
    assert review.ready_for_confirmation is False

    assert "vin_min_v" in review.missing_fields
    assert "vin_max_v" in review.missing_fields
    assert "surge_knowledge" in review.missing_fields
    assert "vout_tolerance_percent" in review.missing_fields
    assert "iout_peak_a" in review.missing_fields
    assert "peak_duration_ms" in review.missing_fields
    assert "ambient_max_c" in review.missing_fields
    assert "thermal_conditions" in review.missing_fields


def test_requirement_review_is_ready_when_minimum_fields_are_complete() -> None:
    card = RequirementCard(
        raw_request=(
            "18-30V input, 24V nominal, no surge expected, "
            "5V ?2%, 2.5A continuous, 3A peak for 10ms, "
            "70C ambient, natural convection"
        ),
        vin_min_v=Decimal("18"),
        vin_nominal_v=Decimal("24"),
        vin_max_v=Decimal("30"),
        surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
        vout_target_v=Decimal("5"),
        vout_tolerance_percent=Decimal("2"),
        iout_continuous_a=Decimal("2.5"),
        iout_peak_a=Decimal("3"),
        peak_duration_ms=Decimal("10"),
        ambient_max_c=Decimal("70"),
        thermal_conditions="natural convection",
        confirmed_by_user=False,
    )

    review = build_requirement_review(card)

    assert review.missing_fields == ()
    assert review.ready_for_confirmation is True
    assert review.card.confirmed_by_user is False


def test_confirm_requirement_card_marks_complete_card_confirmed() -> None:
    card = RequirementCard(
        raw_request="confirmed complete requirement",
        vin_min_v=Decimal("18"),
        vin_nominal_v=Decimal("24"),
        vin_max_v=Decimal("30"),
        surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
        vout_target_v=Decimal("5"),
        vout_tolerance_percent=Decimal("2"),
        iout_continuous_a=Decimal("2.5"),
        iout_peak_a=Decimal("3"),
        peak_duration_ms=Decimal("10"),
        ambient_max_c=Decimal("70"),
        thermal_conditions="natural convection",
        confirmed_by_user=False,
    )

    confirmed = confirm_requirement_card(card)

    assert confirmed is not card
    assert confirmed.confirmed_by_user is True
    assert confirmed.missing_minimum_fields() == ()


def test_confirm_requirement_card_rejects_incomplete_card() -> None:
    card = RequirementCard(
        raw_request="24V to 5V",
        vin_nominal_v=Decimal("24"),
        vout_target_v=Decimal("5"),
        confirmed_by_user=False,
    )

    try:
        confirm_requirement_card(card)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected incomplete requirement confirmation to fail")

    assert "cannot confirm incomplete requirement card" in message
    assert "vin_min_v" in message
    assert "vin_max_v" in message


def test_parser_payload_builds_unconfirmed_card_and_preserves_raw_request() -> None:
    raw_request = "18-30V???24V?????5V???2.5A"

    payload = RequirementParsePayload(
        vin_min_v=Decimal("18"),
        vin_nominal_v=Decimal("24"),
        vin_max_v=Decimal("30"),
        vout_target_v=Decimal("5"),
        iout_continuous_a=Decimal("2.5"),
    )

    card = build_unconfirmed_requirement_card(
        raw_request=raw_request,
        parsed=payload,
    )

    assert card.raw_request == raw_request
    assert card.vin_min_v == Decimal("18")
    assert card.vin_nominal_v == Decimal("24")
    assert card.vout_target_v == Decimal("5")
    assert card.confirmed_by_user is False


def test_parser_payload_cannot_set_user_confirmation() -> None:
    with pytest.raises(ValidationError):
        RequirementParsePayload.model_validate(
            {
                "vin_nominal_v": "24",
                "confirmed_by_user": True,
            }
        )


def test_parse_requirement_payload_json_accepts_strict_json() -> None:
    payload = parse_requirement_payload_json(
        """
        {
          "vin_min_v": 18,
          "vin_nominal_v": 24,
          "vin_max_v": 30,
          "vout_target_v": 5,
          "iout_continuous_a": 2.5
        }
        """
    )

    assert payload.vin_min_v == Decimal("18")
    assert payload.vin_nominal_v == Decimal("24")
    assert payload.vin_max_v == Decimal("30")
    assert payload.vout_target_v == Decimal("5")
    assert payload.iout_continuous_a == Decimal("2.5")


def test_parse_requirement_payload_json_rejects_markdown_fence() -> None:
    response = """```json
    {
      "vin_nominal_v": 24,
      "vout_target_v": 5
    }
    ```"""

    with pytest.raises(ValidationError):
        parse_requirement_payload_json(response)


class FakeRequirementParser:
    def __init__(
        self,
        payload: RequirementParsePayload,
    ) -> None:
        self.payload = payload
        self.seen_raw_request: str | None = None

    def parse(
        self,
        raw_request: str,
    ) -> RequirementParsePayload:
        self.seen_raw_request = raw_request
        return self.payload


def test_parse_requirement_request_builds_unconfirmed_review() -> None:
    raw_request = (
        "18-30V input, 24V nominal, no surge expected, "
        "5V ?2%, 2.5A continuous, 3A peak for 10ms, "
        "70C ambient, natural convection"
    )

    parser = FakeRequirementParser(
        RequirementParsePayload(
            vin_min_v=Decimal("18"),
            vin_nominal_v=Decimal("24"),
            vin_max_v=Decimal("30"),
            surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
            vout_target_v=Decimal("5"),
            vout_tolerance_percent=Decimal("2"),
            iout_continuous_a=Decimal("2.5"),
            iout_peak_a=Decimal("3"),
            peak_duration_ms=Decimal("10"),
            ambient_max_c=Decimal("70"),
            thermal_conditions="natural convection",
        )
    )

    review = parse_requirement_request(
        raw_request=raw_request,
        parser=parser,
    )

    assert parser.seen_raw_request == raw_request
    assert review.card.raw_request == raw_request
    assert review.card.confirmed_by_user is False
    assert review.missing_fields == ()
    assert review.ready_for_confirmation is True


def test_requirement_parser_schema_describes_ambiguous_fields() -> None:
    schema = RequirementParsePayload.model_json_schema()
    properties = schema["properties"]

    assert properties["surge_knowledge"]["description"] == (
        "Input surge status: PRESENT when surge or transient is explicitly present; "
        "NONE_EXPECTED when the user explicitly says no surge is expected; "
        "UNKNOWN when the user explicitly says surge status is unknown; "
        "null only when the user provides no surge information."
    )

    assert properties["peak_duration_ms"]["description"] == (
        "Duration in milliseconds of the explicitly stated peak output current."
    )

    assert properties["ambient_max_c"]["description"] == (
        "Maximum explicitly stated ambient operating temperature in degrees Celsius."
    )

    assert properties["thermal_conditions"]["description"] == (
        "Explicitly stated cooling or thermal condition, such as natural convection, "
        "forced airflow, heatsinking, or PCB thermal constraints."
    )


def test_requirement_review_builds_follow_up_question_for_missing_surge() -> None:
    from local_chip_advisor.requirements import (
        build_requirement_follow_up_questions,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete requirements except surge status.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    assert review.missing_fields == ("surge_knowledge",)
    assert build_requirement_follow_up_questions(review) == (
        "输入端浪涌情况是什么？请选择：存在浪涌、预计不存在额外浪涌、或目前未知。",
    )


def test_requirement_follow_up_groups_missing_input_voltage_fields() -> None:
    from local_chip_advisor.requirements import (
        build_requirement_follow_up_questions,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete requirements except input voltage.",
            "surge_knowledge": "NONE_EXPECTED",
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    assert review.missing_fields == (
        "vin_min_v",
        "vin_nominal_v",
        "vin_max_v",
    )
    assert build_requirement_follow_up_questions(review) == (
        "请输入输入电压范围和标称值，例如：18到30V，标称24V。",
    )


def test_requirement_follow_up_groups_missing_output_voltage_fields() -> None:
    from local_chip_advisor.requirements import (
        build_requirement_follow_up_questions,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete requirements except output voltage.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "surge_knowledge": "NONE_EXPECTED",
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    assert review.missing_fields == (
        "vout_target_v",
        "vout_tolerance_percent",
    )
    assert build_requirement_follow_up_questions(review) == (
        "请输入目标输出电压和允许误差，例如：5V，允许误差±2%。",
    )


def test_requirement_follow_up_groups_missing_output_current_fields() -> None:
    from local_chip_advisor.requirements import (
        build_requirement_follow_up_questions,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete requirements except output current.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "surge_knowledge": "NONE_EXPECTED",
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    assert review.missing_fields == (
        "iout_continuous_a",
        "iout_peak_a",
        "peak_duration_ms",
    )
    assert build_requirement_follow_up_questions(review) == (
        "请输入持续输出电流、峰值电流和峰值持续时间，例如：持续2.5A，峰值3A持续10ms。",
    )


def test_requirement_follow_up_groups_missing_thermal_fields() -> None:
    from local_chip_advisor.requirements import (
        build_requirement_follow_up_questions,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete requirements except thermal conditions.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "surge_knowledge": "NONE_EXPECTED",
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    assert review.missing_fields == (
        "ambient_max_c",
        "thermal_conditions",
    )
    assert build_requirement_follow_up_questions(review) == (
        "请输入最高环境温度和散热条件，例如：最高70°C，自然对流散热。",
    )


def test_requirement_follow_up_groups_missing_surge_detail_fields() -> None:
    from local_chip_advisor.requirements import (
        build_requirement_follow_up_questions,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete requirements except surge details.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "surge_knowledge": "PRESENT",
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    assert review.missing_fields == (
        "surge_voltage_v",
        "surge_duration_ms",
    )
    assert build_requirement_follow_up_questions(review) == (
        "请输入输入浪涌电压和持续时间，例如：浪涌最高36V，持续2ms。",
    )


def test_merge_requirement_follow_up_preserves_existing_fields() -> None:
    from local_chip_advisor.requirements import (
        RequirementParsePayload,
        merge_requirement_follow_up,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Input 18 to 30 V, nominal 24 V, output 5 V.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    parsed_follow_up = RequirementParsePayload.model_validate(
        {
            "surge_knowledge": "NONE_EXPECTED",
        }
    )

    updated = merge_requirement_follow_up(
        card=card,
        parsed=parsed_follow_up,
    )

    assert updated.vin_min_v == 18
    assert updated.vin_nominal_v == 24
    assert updated.vin_max_v == 30
    assert updated.vout_target_v == 5
    assert updated.surge_knowledge is SurgeKnowledge.NONE_EXPECTED
    assert updated.raw_request == card.raw_request
    assert updated.confirmed_by_user is False
    assert updated.missing_minimum_fields() == ()


def test_merge_requirement_follow_up_ignores_null_fields() -> None:
    from local_chip_advisor.requirements import (
        RequirementParsePayload,
        merge_requirement_follow_up,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Input 18 to 30 V, nominal 24 V.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "surge_knowledge": "NONE_EXPECTED",
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": None,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    parsed_follow_up = RequirementParsePayload.model_validate(
        {
            "vin_min_v": None,
            "vin_nominal_v": None,
            "vin_max_v": None,
            "ambient_max_c": 85,
        }
    )

    updated = merge_requirement_follow_up(
        card=card,
        parsed=parsed_follow_up,
    )

    assert updated.vin_min_v == 18
    assert updated.vin_nominal_v == 24
    assert updated.vin_max_v == 30
    assert updated.ambient_max_c == 85
    assert updated.confirmed_by_user is False


def test_merge_requirement_follow_up_does_not_overwrite_existing_fields() -> None:
    from local_chip_advisor.requirements import (
        RequirementParsePayload,
        merge_requirement_follow_up,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Input 18 to 30 V, nominal 24 V, output 5 V.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    parsed_follow_up = RequirementParsePayload.model_validate(
        {
            "vin_min_v": 20,
            "vin_nominal_v": 28,
            "surge_knowledge": "NONE_EXPECTED",
        }
    )

    updated = merge_requirement_follow_up(
        card=card,
        parsed=parsed_follow_up,
    )

    assert updated.vin_min_v == 18
    assert updated.vin_nominal_v == 24
    assert updated.surge_knowledge is SurgeKnowledge.NONE_EXPECTED


def test_merge_requirement_follow_up_rejects_confirmed_card() -> None:
    import pytest

    from local_chip_advisor.requirements import (
        RequirementParsePayload,
        merge_requirement_follow_up,
    )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete confirmed requirement.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "surge_knowledge": "NONE_EXPECTED",
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": True,
        }
    )

    parsed_follow_up = RequirementParsePayload.model_validate(
        {
            "ambient_max_c": 85,
        }
    )

    with pytest.raises(
        ValueError,
        match="cannot merge follow-up into confirmed requirement card",
    ):
        merge_requirement_follow_up(
            card=card,
            parsed=parsed_follow_up,
        )


def test_parse_requirement_follow_up_merges_and_builds_review() -> None:
    from local_chip_advisor.requirements import (
        RequirementParsePayload,
        parse_requirement_follow_up,
    )

    class RecordingParser:
        def __init__(self) -> None:
            self.received: str | None = None

        def parse(self, raw_request: str) -> RequirementParsePayload:
            self.received = raw_request
            return RequirementParsePayload.model_validate(
                {
                    "surge_knowledge": "NONE_EXPECTED",
                }
            )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Input 18 to 30 V, nominal 24 V, output 5 V.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": False,
        }
    )

    parser = RecordingParser()

    review = parse_requirement_follow_up(
        card=card,
        raw_follow_up="No additional input surge is expected.",
        parser=parser,
    )

    assert parser.received == "No additional input surge is expected."
    assert review.card.raw_request == card.raw_request
    assert review.card.surge_knowledge is SurgeKnowledge.NONE_EXPECTED
    assert review.card.confirmed_by_user is False
    assert review.missing_fields == ()
    assert review.ready_for_confirmation is True


def test_parse_requirement_follow_up_keeps_review_incomplete_when_fields_remain() -> None:
    from local_chip_advisor.requirements import (
        RequirementParsePayload,
        parse_requirement_follow_up,
    )

    class StubParser:
        def parse(self, raw_request: str) -> RequirementParsePayload:
            return RequirementParsePayload.model_validate(
                {
                    "surge_knowledge": "NONE_EXPECTED",
                }
            )

    card = RequirementCard.model_validate(
        {
            "raw_request": "Input 18 to 30 V, nominal 24 V.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "confirmed_by_user": False,
        }
    )

    review = parse_requirement_follow_up(
        card=card,
        raw_follow_up="No additional input surge is expected.",
        parser=StubParser(),
    )

    assert review.missing_fields == (
        "iout_continuous_a",
        "iout_peak_a",
        "peak_duration_ms",
        "ambient_max_c",
        "thermal_conditions",
    )
    assert review.ready_for_confirmation is False
    assert review.card.confirmed_by_user is False
