"""Requirement parsing and confirmation workflow contract."""

from decimal import Decimal

from local_chip_advisor.domain import (
    RequirementCard,
    SurgeKnowledge,
)
from local_chip_advisor.requirements import (
    build_requirement_review,
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
