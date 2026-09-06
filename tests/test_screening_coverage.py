"""Guards and behavior tests for requirement-to-screening coverage."""

from dataclasses import dataclass
from decimal import Decimal

import pytest
from test_publication_gate import publishable_draft, reviewed_evidence

from local_chip_advisor.catalog.publication import prepare_published_product
from local_chip_advisor.domain import (
    RequirementCard,
    SurgeKnowledge,
    ThermalCoolingMode,
)
from local_chip_advisor.domain.decision import DEFAULT_REQUIRED_RULE_IDS
from local_chip_advisor.screening import (
    CONTEXT_CLARIFICATION_FIELDS,
    PROCESS_METADATA_FIELDS,
    QUALIFICATION_INPUT_RULES,
    REQUIREMENT_FIELD_COVERAGE,
    evaluate_candidate,
)


def requirement_card(**updates: object) -> RequirementCard:
    values: dict[str, object] = {
        "raw_request": "18-30V input, 5V output, 2.5A continuous",
        "vin_min_v": Decimal(18),
        "vin_nominal_v": Decimal(24),
        "vin_max_v": Decimal(30),
        "surge_knowledge": SurgeKnowledge.NONE_EXPECTED,
        "surge_voltage_v": None,
        "surge_duration_ms": None,
        "vout_target_v": Decimal(5),
        "vout_tolerance_percent": Decimal(2),
        "iout_continuous_a": Decimal("2.5"),
        "iout_peak_a": Decimal(3),
        "peak_duration_ms": Decimal(10),
        "ambient_max_c": Decimal(70),
        "thermal_conditions": "natural convection; normal PCB mounting",
        "cooling_method": ThermalCoolingMode.NATURAL_CONVECTION,
        "confirmed_by_user": True,
    }
    values.update(updates)
    return RequirementCard.model_validate(values)


def check_fingerprints(
    card: RequirementCard,
    *,
    product_updates: dict[str, object] | None = None,
) -> dict[str, tuple[object, ...]]:
    evidence = reviewed_evidence()
    draft = publishable_draft()
    if product_updates:
        draft = draft.model_copy(update=product_updates)
    product = prepare_published_product(
        product=draft,
        evidence=evidence,
    )
    evaluation = evaluate_candidate(
        product=product,
        evidence=evidence,
        requirements=card,
    )
    return {
        check.rule_id: (
            check.state,
            check.requirement,
            check.actual,
            check.reason,
        )
        for check in evaluation.checks
    }


@dataclass(frozen=True)
class QualificationFieldCase:
    left_updates: dict[str, object]
    right_updates: dict[str, object]
    expected_rules: frozenset[str]
    product_updates: dict[str, object] | None = None


QUALIFICATION_FIELD_CASES = {
    "vin_min_v": QualificationFieldCase(
        {"vin_min_v": Decimal(18)},
        {"vin_min_v": Decimal(20)},
        frozenset({"vin.range", "vout.range"}),
    ),
    "vin_max_v": QualificationFieldCase(
        {"vin_max_v": Decimal(30)},
        {"vin_max_v": Decimal(29)},
        frozenset({"vin.range"}),
    ),
    "surge_knowledge": QualificationFieldCase(
        {"surge_knowledge": SurgeKnowledge.NONE_EXPECTED},
        {"surge_knowledge": SurgeKnowledge.UNKNOWN},
        frozenset({"surge.input"}),
    ),
    "surge_voltage_v": QualificationFieldCase(
        {
            "surge_knowledge": SurgeKnowledge.PRESENT,
            "surge_voltage_v": Decimal(40),
            "surge_duration_ms": Decimal(1),
        },
        {
            "surge_knowledge": SurgeKnowledge.PRESENT,
            "surge_voltage_v": Decimal(45),
            "surge_duration_ms": Decimal(1),
        },
        frozenset({"surge.input"}),
    ),
    "surge_duration_ms": QualificationFieldCase(
        {
            "surge_knowledge": SurgeKnowledge.PRESENT,
            "surge_voltage_v": Decimal(40),
            "surge_duration_ms": Decimal(1),
        },
        {
            "surge_knowledge": SurgeKnowledge.PRESENT,
            "surge_voltage_v": Decimal(40),
            "surge_duration_ms": Decimal(2),
        },
        frozenset({"surge.input"}),
    ),
    "vout_target_v": QualificationFieldCase(
        {"vout_target_v": Decimal(5)},
        {"vout_target_v": Decimal("4.5")},
        frozenset({"vout.range"}),
    ),
    "vout_tolerance_percent": QualificationFieldCase(
        {"vout_tolerance_percent": Decimal(2)},
        {"vout_tolerance_percent": Decimal(3)},
        frozenset({"vout.tolerance"}),
    ),
    "iout_continuous_a": QualificationFieldCase(
        {"iout_continuous_a": Decimal(2)},
        {"iout_continuous_a": Decimal("2.5")},
        frozenset({"iout.continuous"}),
    ),
    "iout_peak_a": QualificationFieldCase(
        {"iout_peak_a": Decimal(3)},
        {"iout_peak_a": Decimal("3.5")},
        frozenset({"iout.peak"}),
    ),
    "peak_duration_ms": QualificationFieldCase(
        {"peak_duration_ms": Decimal(10)},
        {"peak_duration_ms": Decimal(20)},
        frozenset({"iout.peak"}),
    ),
    "ambient_max_c": QualificationFieldCase(
        {"ambient_max_c": Decimal(70)},
        {"ambient_max_c": Decimal(75)},
        frozenset({"thermal.ambient", "iout.peak"}),
        {
            "iout_continuous_cooling_method": (
                ThermalCoolingMode.NATURAL_CONVECTION
            ),
            "iout_continuous_ambient_max_c": Decimal(72),
        },
    ),
    "cooling_method": QualificationFieldCase(
        {"cooling_method": ThermalCoolingMode.NATURAL_CONVECTION},
        {"cooling_method": ThermalCoolingMode.FORCED_AIRFLOW},
        frozenset({"thermal.ambient", "iout.peak"}),
        {
            "iout_continuous_cooling_method": (
                ThermalCoolingMode.FORCED_AIRFLOW
            ),
            "iout_continuous_ambient_max_c": Decimal(85),
        },
    ),
}

CONTEXT_FIELD_CASES = {
    "raw_request": ("first user wording", "clarified user wording"),
    "vin_nominal_v": (Decimal(24), Decimal(25)),
    "thermal_conditions": (
        "natural convection; normal PCB mounting",
        "heatsink and PCB construction need clarification",
    ),
}


def test_every_requirement_card_field_is_declared_in_coverage() -> None:
    """Every user condition on RequirementCard is consumed or declared context.

    The coverage map is the single inventory of what screening does with each
    collected requirement field. Adding a requirement field without declaring
    it here (as a rule input or as an intentional context/process-only field)
    fails this guard instead of being silently ignored by the rules.
    """

    assert set(REQUIREMENT_FIELD_COVERAGE) == set(RequirementCard.model_fields)


def test_requirement_fields_are_partitioned_by_screening_role() -> None:
    qualification = set(QUALIFICATION_INPUT_RULES)
    context = set(CONTEXT_CLARIFICATION_FIELDS)
    process = set(PROCESS_METADATA_FIELDS)

    assert qualification.isdisjoint(context)
    assert qualification.isdisjoint(process)
    assert context.isdisjoint(process)
    assert qualification | context | process == set(RequirementCard.model_fields)
    assert PROCESS_METADATA_FIELDS == frozenset({"confirmed_by_user"})
    assert REQUIREMENT_FIELD_COVERAGE == {
        **QUALIFICATION_INPUT_RULES,
        **{field_name: () for field_name in context},
        **{field_name: () for field_name in process},
    }
    assert set(QUALIFICATION_FIELD_CASES) == qualification
    assert set(CONTEXT_FIELD_CASES) == context


def test_coverage_rule_inputs_name_exactly_the_required_rule_set() -> None:
    """Declared rule inputs and the formal gate must name the same rules.

    The equality is deliberate in both directions: a declared input that names
    a rule outside DEFAULT_REQUIRED_RULE_IDS would never gate a decision, and
    a required rule with no requirement-field input would be unanswerable.
    """

    covered_rule_ids = {
        rule_id
        for rule_ids in QUALIFICATION_INPUT_RULES.values()
        for rule_id in rule_ids
    }

    assert covered_rule_ids == set(DEFAULT_REQUIRED_RULE_IDS)


@pytest.mark.parametrize(
    ("field_name", "pair"),
    QUALIFICATION_FIELD_CASES.items(),
)
def test_each_qualification_field_changes_only_declared_rules(
    field_name: str,
    pair: QualificationFieldCase,
) -> None:
    left = check_fingerprints(
        requirement_card(**pair.left_updates),
        product_updates=pair.product_updates,
    )
    right = check_fingerprints(
        requirement_card(**pair.right_updates),
        product_updates=pair.product_updates,
    )
    changed_rules = {
        rule_id
        for rule_id in DEFAULT_REQUIRED_RULE_IDS
        if left[rule_id] != right[rule_id]
    }
    expected_rules = set(pair.expected_rules)

    assert set(QUALIFICATION_INPUT_RULES[field_name]) == expected_rules
    assert changed_rules == expected_rules


@pytest.mark.parametrize(
    ("field_name", "left_value", "right_value"),
    tuple(
        (field_name, values[0], values[1])
        for field_name, values in CONTEXT_FIELD_CASES.items()
    ),
)
def test_context_fields_are_preserved_without_changing_qualification_checks(
    field_name: str,
    left_value: object,
    right_value: object,
) -> None:
    left_card = requirement_card(**{field_name: left_value})
    right_card = requirement_card(**{field_name: right_value})

    assert getattr(left_card, field_name) == left_value
    assert getattr(right_card, field_name) == right_value
    assert check_fingerprints(left_card) == check_fingerprints(right_card)


def test_nominal_input_context_remains_cross_field_validated() -> None:
    with pytest.raises(ValueError, match="vin_min <= vin_nominal <= vin_max"):
        requirement_card(vin_nominal_v=Decimal(31))


def test_unconfirmed_card_is_rejected_before_screening() -> None:
    evidence = reviewed_evidence()
    product = prepare_published_product(
        product=publishable_draft(),
        evidence=evidence,
    )

    with pytest.raises(ValueError, match="confirmed by the user"):
        evaluate_candidate(
            product=product,
            evidence=evidence,
            requirements=requirement_card(confirmed_by_user=False),
        )
