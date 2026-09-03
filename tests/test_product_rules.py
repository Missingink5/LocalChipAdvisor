"""Contract tests for deterministic Buck product screening rules."""

from decimal import Decimal

from local_chip_advisor.domain import CheckState
from local_chip_advisor.domain.product_rules import check_continuous_output_current, check_input_voltage, check_output_voltage
from test_product_record import valid_product


def test_dynamic_vout_limit_fails_when_target_exceeds_limit_at_vin_min() -> None:
    product = valid_product(
        vin_min_v="4.5",
        vout_min_v="1",
        vout_max_v=None,
        vout_max_vin_ratio="0.9",
        evidence_ids_by_field=(
            ("vout_min_v", ("ev:mp4570:vout-range",)),
            ("vout_max_vin_ratio", ("ev:mp4570:vout-range",)),
        ),
    )

    result = check_output_voltage(
        product=product,
        requested_vout_v=Decimal("5"),
        operating_vin_min_v=Decimal("4.5"),
    )

    assert result.state is CheckState.FAIL
    assert result.actual == "1V to 4.05V at VIN=4.5V"
    assert result.evidence_ids == ("ev:mp4570:vout-range",)


def test_dynamic_vout_limit_passes_when_target_is_inside_range() -> None:
    product = valid_product(
        vin_min_v="4.5",
        vout_min_v="1",
        vout_max_v=None,
        vout_max_vin_ratio="0.9",
        evidence_ids_by_field=(
            ("vout_min_v", ("ev:mp4570:vout-range",)),
            ("vout_max_vin_ratio", ("ev:mp4570:vout-range",)),
        ),
    )

    result = check_output_voltage(
        product=product,
        requested_vout_v=Decimal("3.3"),
        operating_vin_min_v=Decimal("4.5"),
    )

    assert result.state is CheckState.PASS
    assert result.actual == "1V to 4.05V at VIN=4.5V"
    assert result.evidence_ids == ("ev:mp4570:vout-range",)


def test_output_voltage_is_unknown_when_decisive_evidence_is_missing() -> None:
    product = valid_product(
        vin_min_v="4.5",
        vout_min_v="1",
        vout_max_v=None,
        vout_max_vin_ratio="0.9",
        evidence_ids_by_field=(),
    )

    result = check_output_voltage(
        product=product,
        requested_vout_v=Decimal("3.3"),
        operating_vin_min_v=Decimal("4.5"),
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()


def test_input_voltage_passes_when_operating_range_is_inside_product_range() -> None:
    product = valid_product(
        vin_min_v="4.5",
        vin_max_v="55",
        evidence_ids_by_field=(
            ("vin_min_v", ("ev:mp4570:vin-range",)),
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    result = check_input_voltage(
        product=product,
        operating_vin_min_v=Decimal("18"),
        operating_vin_max_v=Decimal("30"),
    )

    assert result.state is CheckState.PASS
    assert result.actual == "4.5V to 55V"
    assert result.evidence_ids == ("ev:mp4570:vin-range",)


def test_input_voltage_fails_when_operating_max_exceeds_product_range() -> None:
    product = valid_product(
        vin_min_v="4.5",
        vin_max_v="55",
        evidence_ids_by_field=(
            ("vin_min_v", ("ev:mp4570:vin-range",)),
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    result = check_input_voltage(
        product=product,
        operating_vin_min_v=Decimal("18"),
        operating_vin_max_v=Decimal("60"),
    )

    assert result.state is CheckState.FAIL
    assert result.actual == "4.5V to 55V"
    assert result.evidence_ids == ("ev:mp4570:vin-range",)


def test_input_voltage_is_unknown_when_decisive_evidence_is_missing() -> None:
    product = valid_product(
        vin_min_v="4.5",
        vin_max_v="55",
        evidence_ids_by_field=(),
    )

    result = check_input_voltage(
        product=product,
        operating_vin_min_v=Decimal("18"),
        operating_vin_max_v=Decimal("30"),
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()


def test_continuous_output_current_passes_at_rated_limit() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:mp4570:iout",)),
        ),
    )

    result = check_continuous_output_current(
        product=product,
        requested_iout_a=Decimal("3"),
    )

    assert result.state is CheckState.PASS
    assert result.actual == "3A continuous rated maximum"
    assert result.evidence_ids == ("ev:mp4570:iout",)


def test_continuous_output_current_fails_above_rated_limit() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:mp4570:iout",)),
        ),
    )

    result = check_continuous_output_current(
        product=product,
        requested_iout_a=Decimal("3.5"),
    )

    assert result.state is CheckState.FAIL
    assert result.actual == "3A continuous rated maximum"
    assert result.evidence_ids == ("ev:mp4570:iout",)


def test_continuous_output_current_is_unknown_without_evidence() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        evidence_ids_by_field=(),
    )

    result = check_continuous_output_current(
        product=product,
        requested_iout_a=Decimal("2"),
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
