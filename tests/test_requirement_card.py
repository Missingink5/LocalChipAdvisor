"""The system must not silently invent or skip minimum user requirements."""

import pytest
from pydantic import ValidationError

from local_chip_advisor.domain import RequirementCard, SurgeKnowledge


def complete_card(**overrides: object) -> RequirementCard:
    values: dict[str, object] = {
        "raw_request": "Test-only 24 V to 5 V industrial requirement",
        "vin_min_v": "18",
        "vin_nominal_v": "24",
        "vin_max_v": "30",
        "surge_knowledge": SurgeKnowledge.NONE_EXPECTED,
        "vout_target_v": "5",
        "vout_tolerance_percent": "2",
        "iout_continuous_a": "3",
        "iout_peak_a": "4",
        "peak_duration_ms": "100",
        "ambient_max_c": "70",
        "thermal_conditions": "Four-layer PCB; airflow not specified",
        "confirmed_by_user": True,
    }
    values.update(overrides)
    return RequirementCard.model_validate(values)


def test_complete_confirmed_card_is_accepted() -> None:
    assert complete_card().missing_minimum_fields() == ()


def test_incomplete_card_can_exist_but_cannot_be_confirmed() -> None:
    draft = RequirementCard(raw_request="24 V to 5 V")
    assert "vin_min_v" in draft.missing_minimum_fields()

    with pytest.raises(ValidationError, match="confirmed requirement card is incomplete"):
        RequirementCard(raw_request="24 V to 5 V", confirmed_by_user=True)


def test_present_surge_requires_voltage_and_duration() -> None:
    with pytest.raises(ValidationError, match="surge_voltage_v"):
        complete_card(surge_knowledge=SurgeKnowledge.PRESENT)


def test_unknown_surge_is_explicit_not_silently_defaulted() -> None:
    card = complete_card(surge_knowledge=SurgeKnowledge.UNKNOWN)
    assert card.surge_knowledge is SurgeKnowledge.UNKNOWN
    assert card.surge_voltage_v is None


def test_invalid_input_voltage_order_is_rejected() -> None:
    with pytest.raises(ValidationError, match="vin_min <= vin_nominal <= vin_max"):
        complete_card(vin_min_v="30", vin_nominal_v="24", vin_max_v="18")


def test_peak_current_below_continuous_is_rejected() -> None:
    with pytest.raises(ValidationError, match="peak output current"):
        complete_card(iout_continuous_a="4", iout_peak_a="3")


def test_surge_values_are_rejected_when_surge_is_not_present() -> None:
    with pytest.raises(ValidationError, match="surge values require"):
        complete_card(
            surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
            surge_voltage_v="36",
            surge_duration_ms="10",
        )
