"""Contract tests for deterministic Buck product screening rules."""

from decimal import Decimal

from local_chip_advisor.domain import CheckState, SurgeKnowledge
from local_chip_advisor.domain.product_rules import check_continuous_output_current, check_input_surge, check_input_voltage, check_output_voltage, check_peak_output_current, check_ambient_thermal
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

def test_input_surge_passes_when_user_confirms_none_expected() -> None:
    product = valid_product(
        vin_max_v="55",
        vin_absolute_max_v="60",
        evidence_ids_by_field=(
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    result = check_input_surge(
        product=product,
        surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
        surge_voltage_v=None,
        surge_duration_ms=None,
    )

    assert result.rule_id == "surge.input"
    assert result.field_name == "vin.range"
    assert result.state is CheckState.PASS
    assert result.evidence_ids == ("ev:mp4570:vin-range",)


def test_input_surge_is_unknown_when_real_surge_has_no_transient_rating() -> None:
    product = valid_product(
        vin_max_v="55",
        vin_absolute_max_v="60",
        evidence_ids_by_field=(
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    result = check_input_surge(
        product=product,
        surge_knowledge=SurgeKnowledge.PRESENT,
        surge_voltage_v=Decimal("58"),
        surge_duration_ms=Decimal("1"),
    )

    assert result.rule_id == "surge.input"
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()

def test_peak_output_current_passes_with_explicit_current_and_duration_rating() -> None:
    product = valid_product(
        iout_peak_max_a="4",
        iout_peak_duration_max_ms="10",
        evidence_ids_by_field=(
            ("iout_peak_max_a", ("ev:peak",)),
            ("iout_peak_duration_max_ms", ("ev:peak",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal("3.5"),
        requested_peak_duration_ms=Decimal("5"),
    )

    assert result.rule_id == "iout.peak"
    assert result.state is CheckState.PASS
    assert result.evidence_ids == ("ev:peak",)


def test_peak_output_current_fails_when_current_exceeds_rating() -> None:
    product = valid_product(
        iout_peak_max_a="4",
        iout_peak_duration_max_ms="10",
        evidence_ids_by_field=(
            ("iout_peak_max_a", ("ev:peak",)),
            ("iout_peak_duration_max_ms", ("ev:peak",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal("4.5"),
        requested_peak_duration_ms=Decimal("5"),
    )

    assert result.state is CheckState.FAIL


def test_peak_output_current_fails_when_duration_exceeds_rating() -> None:
    product = valid_product(
        iout_peak_max_a="4",
        iout_peak_duration_max_ms="10",
        evidence_ids_by_field=(
            ("iout_peak_max_a", ("ev:peak",)),
            ("iout_peak_duration_max_ms", ("ev:peak",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal("3.5"),
        requested_peak_duration_ms=Decimal("20"),
    )

    assert result.state is CheckState.FAIL


def test_peak_output_current_is_unknown_without_duration_rating() -> None:
    product = valid_product(
        iout_peak_max_a="4",
        evidence_ids_by_field=(
            ("iout_peak_max_a", ("ev:peak",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal("3.5"),
        requested_peak_duration_ms=Decimal("5"),
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()

def test_ambient_thermal_passes_with_explicit_ambient_rating() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal("70"),
        thermal_conditions="natural convection; normal PCB mounting",
    )

    assert result.rule_id == "thermal.ambient"
    assert result.state is CheckState.PASS
    assert result.evidence_ids == ("ev:ambient",)


def test_ambient_thermal_fails_above_explicit_ambient_rating() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal("100"),
        thermal_conditions="natural convection; normal PCB mounting",
    )

    assert result.state is CheckState.FAIL


def test_ambient_thermal_is_unknown_when_only_junction_rating_exists() -> None:
    product = valid_product(
        junction_temp_max_c="125",
        evidence_ids_by_field=(
            ("junction_temp_max_c", ("ev:tj",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal("70"),
        thermal_conditions="natural convection; normal PCB mounting",
    )

    assert result.rule_id == "thermal.ambient"
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()

def test_peak_output_current_uses_continuous_rating_when_it_is_sufficient() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        iout_peak_max_a=None,
        iout_peak_duration_max_ms=None,
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:continuous",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal("3"),
        requested_peak_duration_ms=Decimal("10"),
    )

    assert result.rule_id == "iout.peak"
    assert result.field_name == "iout.continuous"
    assert result.state is CheckState.PASS
    assert result.evidence_ids == ("ev:continuous",)
