"""Contract tests for deterministic Buck product screening rules."""

from decimal import Decimal

import pytest
from test_product_record import valid_product

from local_chip_advisor.domain import (
    CheckState,
    SurgeKnowledge,
    ThermalCoolingMode,
)
from local_chip_advisor.domain.product_rules import (
    check_ambient_thermal,
    check_continuous_output_current,
    check_input_surge,
    check_input_voltage,
    check_output_tolerance,
    check_output_voltage,
    check_peak_output_current,
)


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
        requested_vout_v=Decimal(5),
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
        operating_vin_min_v=Decimal(18),
        operating_vin_max_v=Decimal(30),
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
        operating_vin_min_v=Decimal(18),
        operating_vin_max_v=Decimal(60),
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
        operating_vin_min_v=Decimal(18),
        operating_vin_max_v=Decimal(30),
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
        requested_iout_a=Decimal(3),
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
        requested_iout_a=Decimal(2),
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
        surge_voltage_v=Decimal(58),
        surge_duration_ms=Decimal(1),
    )

    assert result.rule_id == "surge.input"
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()


def test_absolute_maximum_vin_is_not_a_transient_pass() -> None:
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
        surge_voltage_v=Decimal(58),
        surge_duration_ms=Decimal(1),
    )

    # 58V sits below the 60V Absolute Maximum, yet that limit is not an
    # operating transient rating and must never be shown as a PASS.
    assert result.state is CheckState.UNKNOWN
    assert "not treated as a transient operating rating" in result.reason
    assert "Absolute Maximum VIN=60V" in result.reason
    assert result.evidence_ids == ()


def test_present_surge_within_recommended_range_is_still_unknown() -> None:
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
        surge_voltage_v=Decimal(50),
        surge_duration_ms=Decimal(1),
    )

    # Staying inside the recommended operating range is not a transient
    # surge qualification either: a real surge needs its own transient model.
    assert result.state is CheckState.UNKNOWN
    assert "not structurally qualified" in result.reason
    assert result.evidence_ids == ()


def test_explicitly_unknown_surge_knowledge_is_not_none_expected() -> None:
    product = valid_product(
        vin_max_v="55",
        vin_absolute_max_v="60",
        evidence_ids_by_field=(
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    result = check_input_surge(
        product=product,
        surge_knowledge=SurgeKnowledge.UNKNOWN,
        surge_voltage_v=None,
        surge_duration_ms=None,
    )

    # "No surge characterized yet" is a distinct state from the user's
    # explicit NONE_EXPECTED confirmation; it cannot grant a PASS.
    assert result.rule_id == "surge.input"
    assert result.field_name == "surge.input"
    assert result.state is CheckState.UNKNOWN
    assert "has not characterized" in result.reason
    assert result.evidence_ids == ()


def test_none_expected_still_needs_reviewed_input_voltage_evidence() -> None:
    product = valid_product(
        vin_max_v="55",
        evidence_ids_by_field=(),
    )

    result = check_input_surge(
        product=product,
        surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
        surge_voltage_v=None,
        surge_duration_ms=None,
    )

    # Even with no surge expected, the PASS is bound to the decisive normal
    # input-voltage evidence rather than to an unproven claim.
    assert result.state is CheckState.UNKNOWN
    assert "decisive normal input-voltage evidence" in result.reason
    assert result.evidence_ids == ()


def test_none_expected_rejects_surge_values() -> None:
    product = valid_product(
        vin_max_v="55",
        evidence_ids_by_field=(
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    with pytest.raises(ValueError, match="must be omitted"):
        check_input_surge(
            product=product,
            surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
            surge_voltage_v=Decimal(58),
            surge_duration_ms=None,
        )


def test_present_surge_requires_voltage_and_duration() -> None:
    product = valid_product(
        vin_max_v="55",
        evidence_ids_by_field=(
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    with pytest.raises(ValueError, match="requires"):
        check_input_surge(
            product=product,
            surge_knowledge=SurgeKnowledge.PRESENT,
            surge_voltage_v=Decimal(58),
            surge_duration_ms=None,
        )


def test_input_surge_rejects_non_positive_transient_values() -> None:
    product = valid_product(
        vin_max_v="55",
        evidence_ids_by_field=(
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    with pytest.raises(ValueError, match="must be positive"):
        check_input_surge(
            product=product,
            surge_knowledge=SurgeKnowledge.PRESENT,
            surge_voltage_v=Decimal(0),
            surge_duration_ms=Decimal(1),
        )

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
        requested_peak_duration_ms=Decimal(5),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
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
        requested_peak_duration_ms=Decimal(5),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
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
        requested_peak_duration_ms=Decimal(20),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
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
        requested_peak_duration_ms=Decimal(5),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()

def test_ambient_thermal_passes_with_explicit_ambient_rating() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        ambient_cooling_method="NATURAL_CONVECTION",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal(70),
        cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
    )

    assert result.rule_id == "thermal.ambient"
    assert result.state is CheckState.PASS
    assert result.evidence_ids == ("ev:ambient",)


def test_ambient_thermal_fails_above_explicit_ambient_rating() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        ambient_cooling_method="NATURAL_CONVECTION",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal(100),
        cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
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
        ambient_max_c=Decimal(70),
        cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
    )

    assert result.rule_id == "thermal.ambient"
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()


def test_ambient_thermal_is_unknown_when_user_cooling_is_unstated() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        ambient_cooling_method="NATURAL_CONVECTION",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal(70),
        cooling_method=None,
    )

    # A numeric value is not enough: 70°C inside an 85°C rating says nothing
    # until the user's operating regime is structurally characterized.
    assert result.rule_id == "thermal.ambient"
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "not structurally characterized" in result.reason


def test_ambient_thermal_is_unknown_when_product_regime_is_unstated() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal(70),
        cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
    )

    # The explicit evidence may only be used within its stated applicability;
    # an unqualified rating cannot be extended to any user regime.
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "not structurally stated" in result.reason


def test_forced_airflow_rating_does_not_prove_natural_convection() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        ambient_cooling_method="FORCED_AIRFLOW",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal(70),
        cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "characterized under FORCED_AIRFLOW" in result.reason


def test_forced_airflow_rating_fails_above_its_own_regime() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        ambient_cooling_method="FORCED_AIRFLOW",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal(100),
        cooling_method=ThermalCoolingMode.FORCED_AIRFLOW,
    )

    assert result.state is CheckState.FAIL


def test_natural_convection_rating_covers_forced_airflow_within_limit() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        ambient_cooling_method="NATURAL_CONVECTION",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal(70),
        cooling_method=ThermalCoolingMode.FORCED_AIRFLOW,
    )

    # Natural convection is the harder regime; a natural-convection rating
    # also covers forced-airflow operation up to its numeric value.
    assert result.state is CheckState.PASS


def test_natural_rating_does_not_bound_forced_airflow_above_it() -> None:
    product = valid_product(
        ambient_temp_max_c="85",
        ambient_cooling_method="NATURAL_CONVECTION",
        evidence_ids_by_field=(
            ("ambient_temp_max_c", ("ev:ambient",)),
        ),
    )

    result = check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal(100),
        cooling_method=ThermalCoolingMode.FORCED_AIRFLOW,
    )

    # Above a natural-convection rating the forced-airflow limit is unknown;
    # calling it a known failure would overreach the evidence.
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()


def test_peak_output_current_uses_continuous_rating_when_it_is_sufficient() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        iout_continuous_cooling_method="NATURAL_CONVECTION",
        iout_continuous_ambient_max_c="85",
        iout_peak_max_a=None,
        iout_peak_duration_max_ms=None,
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:continuous",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal(3),
        requested_peak_duration_ms=Decimal(10),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
        requested_ambient_max_c=Decimal(70),
    )

    assert result.rule_id == "iout.peak"
    assert result.field_name == "iout.continuous"
    assert result.state is CheckState.PASS
    assert result.evidence_ids == ("ev:continuous",)


def test_peak_fallback_is_unknown_when_user_cooling_regime_is_unstated() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        iout_continuous_cooling_method="NATURAL_CONVECTION",
        iout_continuous_ambient_max_c="85",
        iout_peak_max_a=None,
        iout_peak_duration_max_ms=None,
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:continuous",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal(3),
        requested_peak_duration_ms=Decimal(10),
        requested_cooling_method=None,
        requested_ambient_max_c=Decimal(70),
    )

    assert result.rule_id == "iout.peak"
    assert result.field_name == "iout.continuous"
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "cooling regime" in result.reason


def test_peak_fallback_is_unknown_when_rating_regime_is_unstated() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        iout_continuous_ambient_max_c="85",
        iout_peak_max_a=None,
        iout_peak_duration_max_ms=None,
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:continuous",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal(3),
        requested_peak_duration_ms=Decimal(10),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
        requested_ambient_max_c=Decimal(70),
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "cooling regime" in result.reason


def test_peak_fallback_forced_airflow_rating_does_not_prove_natural_convection() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        iout_continuous_cooling_method="FORCED_AIRFLOW",
        iout_continuous_ambient_max_c="85",
        iout_peak_max_a=None,
        iout_peak_duration_max_ms=None,
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:continuous",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal(3),
        requested_peak_duration_ms=Decimal(10),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
        requested_ambient_max_c=Decimal(70),
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "FORCED_AIRFLOW" in result.reason
    assert "NATURAL_CONVECTION" in result.reason


def test_peak_fallback_natural_convection_rating_covers_forced_airflow_request() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        iout_continuous_cooling_method="NATURAL_CONVECTION",
        iout_continuous_ambient_max_c="85",
        iout_peak_max_a=None,
        iout_peak_duration_max_ms=None,
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:continuous",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal(3),
        requested_peak_duration_ms=Decimal(10),
        requested_cooling_method=ThermalCoolingMode.FORCED_AIRFLOW,
        requested_ambient_max_c=Decimal(70),
    )

    assert result.state is CheckState.PASS
    assert result.evidence_ids == ("ev:continuous",)


def test_peak_fallback_is_unknown_when_rating_ambient_applicability_is_unstated() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        iout_continuous_cooling_method="NATURAL_CONVECTION",
        iout_peak_max_a=None,
        iout_peak_duration_max_ms=None,
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:continuous",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal(3),
        requested_peak_duration_ms=Decimal(10),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
        requested_ambient_max_c=Decimal(70),
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "ambient" in result.reason


def test_peak_fallback_is_unknown_when_requested_ambient_exceeds_rating_applicability() -> None:
    product = valid_product(
        iout_continuous_max_a="3",
        iout_continuous_cooling_method="NATURAL_CONVECTION",
        iout_continuous_ambient_max_c="60",
        iout_peak_max_a=None,
        iout_peak_duration_max_ms=None,
        evidence_ids_by_field=(
            ("iout_continuous_max_a", ("ev:continuous",)),
        ),
    )

    result = check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal(3),
        requested_peak_duration_ms=Decimal(10),
        requested_cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
        requested_ambient_max_c=Decimal(70),
    )

    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "60" in result.reason
    assert "70" in result.reason


def test_output_tolerance_rule_api_exists() -> None:
    from importlib import import_module

    rules = import_module(
        "local_chip_advisor.domain.product_rules"
    )

    assert hasattr(
        rules,
        "check_output_tolerance",
    )


def test_output_tolerance_is_unknown_without_structured_accuracy_capability() -> None:
    product = valid_product(
        feedback_reference_v=None,
        evidence_ids_by_field=(),
    )

    result = check_output_tolerance(
        product=product,
        requested_tolerance_percent=Decimal(2),
    )

    assert result.rule_id == "vout.tolerance"
    assert result.field_name == "vout.tolerance"
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()


def test_output_tolerance_rejects_non_positive_request() -> None:
    product = valid_product()

    with pytest.raises(ValueError, match="must be positive"):
        check_output_tolerance(
            product=product,
            requested_tolerance_percent=Decimal(0),
        )


def test_feedback_reference_voltage_does_not_prove_total_output_error() -> None:
    product = valid_product(
        feedback_reference_v="0.6",
        evidence_ids_by_field=(
            ("feedback_reference_v", ("ev:ref",)),
        ),
    )

    result = check_output_tolerance(
        product=product,
        requested_tolerance_percent=Decimal(2),
    )

    assert result.rule_id == "vout.tolerance"
    assert result.state is CheckState.UNKNOWN
    assert result.evidence_ids == ()
    assert "not a guaranteed" in result.reason
    assert result.actual is not None
    assert "0.6" in result.actual
