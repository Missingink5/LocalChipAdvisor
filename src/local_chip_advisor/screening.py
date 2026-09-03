"""Application-level deterministic screening orchestration."""

from __future__ import annotations

from collections.abc import Iterable

from local_chip_advisor.domain import (
    CandidateEvaluation,
    EvidenceRef,
    RequirementCard,
    classify_candidate,
    validate_evidence_bindings,
)
from local_chip_advisor.domain.product import BuckProductRecord
from local_chip_advisor.domain.product_rules import (
    check_ambient_thermal,
    check_continuous_output_current,
    check_input_surge,
    check_input_voltage,
    check_output_voltage,
    check_peak_output_current,
)


def evaluate_candidate(
    *,
    product: BuckProductRecord,
    evidence: Iterable[EvidenceRef],
    requirements: RequirementCard,
) -> CandidateEvaluation:
    """Run all required hard rules and validate decisive evidence."""

    if not requirements.confirmed_by_user:
        raise ValueError(
            "requirements must be confirmed by the user before screening"
        )

    missing = requirements.missing_minimum_fields()
    if missing:
        raise ValueError(
            "confirmed requirements are incomplete: "
            + ", ".join(missing)
        )

    # RequirementCard validation guarantees these are present once confirmed.
    assert requirements.vin_min_v is not None
    assert requirements.vin_max_v is not None
    assert requirements.vout_target_v is not None
    assert requirements.iout_continuous_a is not None
    assert requirements.iout_peak_a is not None
    assert requirements.peak_duration_ms is not None
    assert requirements.surge_knowledge is not None
    assert requirements.ambient_max_c is not None
    assert requirements.thermal_conditions is not None

    checks = (
        check_input_voltage(
            product=product,
            operating_vin_min_v=requirements.vin_min_v,
            operating_vin_max_v=requirements.vin_max_v,
        ),
        check_output_voltage(
            product=product,
            requested_vout_v=requirements.vout_target_v,
            operating_vin_min_v=requirements.vin_min_v,
        ),
        check_continuous_output_current(
            product=product,
            requested_iout_a=requirements.iout_continuous_a,
        ),
        check_peak_output_current(
            product=product,
            requested_iout_peak_a=requirements.iout_peak_a,
            requested_peak_duration_ms=requirements.peak_duration_ms,
        ),
        check_input_surge(
            product=product,
            surge_knowledge=requirements.surge_knowledge,
            surge_voltage_v=requirements.surge_voltage_v,
            surge_duration_ms=requirements.surge_duration_ms,
        ),
        check_ambient_thermal(
            product=product,
            ambient_max_c=requirements.ambient_max_c,
            thermal_conditions=requirements.thermal_conditions,
        ),
    )

    evaluation = classify_candidate(
        product_id=product.product_id,
        publication_status=product.publication_status,
        checks=checks,
    )

    evidence_items = tuple(evidence)
    evidence_by_id = {
        item.evidence_id: item
        for item in evidence_items
    }

    if len(evidence_by_id) != len(evidence_items):
        raise ValueError("duplicate evidence_id supplied")

    validate_evidence_bindings(
        evaluation,
        evidence_by_id,
        knowledge_base_version=product.knowledge_base_version,
    )

    return evaluation
