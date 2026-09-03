"""Requirement parsing and confirmation workflow contract."""

from decimal import Decimal

from local_chip_advisor.domain import (
    RequirementCard,
    SurgeKnowledge,
)
from local_chip_advisor.requirements import (
    build_requirement_review,
    confirm_requirement_card,
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
