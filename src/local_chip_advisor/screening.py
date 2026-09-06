"""Application-level deterministic screening orchestration."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from local_chip_advisor.catalog.sqlite_store import (
    list_published_products,
    load_published_catalog,
)
from local_chip_advisor.domain import (
    CandidateBucket,
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
    check_output_tolerance,
    check_output_voltage,
    check_peak_output_current,
)

#: Requirement fields that may change deterministic qualification checks.
#: Conditional surge values feed ``surge.input`` only when a surge is PRESENT.
QUALIFICATION_INPUT_RULES: Mapping[str, tuple[str, ...]] = {
    "vin_min_v": ("vin.range", "vout.range"),
    "vin_max_v": ("vin.range",),
    "surge_knowledge": ("surge.input",),
    "surge_voltage_v": ("surge.input",),  # only when surge_knowledge is PRESENT
    "surge_duration_ms": ("surge.input",),  # only when surge_knowledge is PRESENT
    "vout_target_v": ("vout.range",),
    "vout_tolerance_percent": ("vout.tolerance",),
    "iout_continuous_a": ("iout.continuous",),
    "iout_peak_a": ("iout.peak",),
    "peak_duration_ms": ("iout.peak",),
    "ambient_max_c": ("thermal.ambient", "iout.peak"),
    "cooling_method": (
        "thermal.ambient",
        "iout.peak",
    ),
}

#: Inputs retained for traceability, clarification, or cross-field validation.
#: They cannot directly change qualification checks in the current rule set.
CONTEXT_CLARIFICATION_FIELDS = frozenset(
    {
        "raw_request",
        "vin_nominal_v",
        "thermal_conditions",
    }
)

#: Workflow metadata enforced before qualification rules execute.
PROCESS_METADATA_FIELDS = frozenset({"confirmed_by_user"})

#: Complete inventory used by the schema-drift guard. The explicit categories
#: prevent context and process fields from being mistaken for unused rule input.
REQUIREMENT_FIELD_COVERAGE: Mapping[str, tuple[str, ...]] = {
    **QUALIFICATION_INPUT_RULES,
    **{field_name: () for field_name in CONTEXT_CLARIFICATION_FIELDS},
    **{field_name: () for field_name in PROCESS_METADATA_FIELDS},
}


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
    assert requirements.vout_tolerance_percent is not None
    assert requirements.iout_continuous_a is not None
    assert requirements.iout_peak_a is not None
    assert requirements.peak_duration_ms is not None
    assert requirements.surge_knowledge is not None
    assert requirements.ambient_max_c is not None

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
        check_output_tolerance(
            product=product,
            requested_tolerance_percent=requirements.vout_tolerance_percent,
        ),
        check_continuous_output_current(
            product=product,
            requested_iout_a=requirements.iout_continuous_a,
        ),
        check_peak_output_current(
            product=product,
            requested_iout_peak_a=requirements.iout_peak_a,
            requested_peak_duration_ms=requirements.peak_duration_ms,
            requested_cooling_method=requirements.cooling_method,
            requested_ambient_max_c=requirements.ambient_max_c,
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
            cooling_method=requirements.cooling_method,
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


@dataclass(frozen=True, slots=True)
class ScreenedCandidate:
    """One screened product with its evaluation and reviewed evidence."""

    product: BuckProductRecord
    evaluation: CandidateEvaluation
    evidence: tuple[EvidenceRef, ...]

    @property
    def product_id(self) -> str:
        """Compatibility shortcut for bucket consumers."""

        return self.evaluation.product_id


@dataclass(frozen=True, slots=True)
class CatalogScreeningResult:
    """Deterministic three-bucket result for one published catalog."""

    formal: tuple[ScreenedCandidate, ...]
    near_match: tuple[ScreenedCandidate, ...]
    needs_verification: tuple[ScreenedCandidate, ...]


def screen_published_catalog(
    *,
    database_path: str | Path,
    knowledge_base_version: str,
    requirements: RequirementCard,
) -> CatalogScreeningResult:
    """Evaluate every published product without discarding near matches."""

    products = list_published_products(
        database_path=database_path,
        knowledge_base_version=knowledge_base_version,
    )

    formal: list[ScreenedCandidate] = []
    near_match: list[ScreenedCandidate] = []
    needs_verification: list[ScreenedCandidate] = []

    for product in products:
        loaded_product, evidence = load_published_catalog(
            database_path=database_path,
            product_id=product.product_id,
            knowledge_base_version=product.knowledge_base_version,
        )

        evaluation = evaluate_candidate(
            product=loaded_product,
            evidence=evidence,
            requirements=requirements,
        )

        screened = ScreenedCandidate(
            product=loaded_product,
            evaluation=evaluation,
            evidence=tuple(evidence),
        )

        if evaluation.bucket is CandidateBucket.FORMAL:
            formal.append(screened)
        elif evaluation.bucket is CandidateBucket.NEAR_MATCH:
            near_match.append(screened)
        elif evaluation.bucket is CandidateBucket.NEEDS_VERIFICATION:
            needs_verification.append(screened)
        else:
            raise ValueError(
                f"unsupported candidate bucket: {evaluation.bucket}"
            )

    return CatalogScreeningResult(
        formal=tuple(formal),
        near_match=tuple(near_match),
        needs_verification=tuple(needs_verification),
    )
