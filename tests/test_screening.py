"""Application-level deterministic candidate screening."""

from decimal import Decimal
from pathlib import Path

from test_publication_gate import publishable_draft, reviewed_evidence

from local_chip_advisor.catalog.publication import prepare_published_product
from local_chip_advisor.catalog.sqlite_store import save_published_catalog
from local_chip_advisor.domain import (
    CandidateBucket,
    CheckState,
    LimitKind,
    RequirementCard,
    SurgeKnowledge,
    ThermalCoolingMode,
)
from local_chip_advisor.domain.decision import DEFAULT_REQUIRED_RULE_IDS
from local_chip_advisor.domain.product import BuckProductRecord
from local_chip_advisor.screening import (
    evaluate_candidate,
    screen_published_catalog,
)


def confirmed_requirements() -> RequirementCard:
    return RequirementCard(
        raw_request="18-30V input, 5V output, 2.5A continuous, 3A peak for 10ms",
        vin_min_v=Decimal(18),
        vin_nominal_v=Decimal(24),
        vin_max_v=Decimal(30),
        surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
        vout_target_v=Decimal(5),
        vout_tolerance_percent=Decimal(2),
        iout_continuous_a=Decimal("2.5"),
        iout_peak_a=Decimal(3),
        peak_duration_ms=Decimal(10),
        ambient_max_c=Decimal(70),
        thermal_conditions="natural convection; normal PCB mounting",
        cooling_method=ThermalCoolingMode.NATURAL_CONVECTION,
        confirmed_by_user=True,
    )


def test_published_candidate_runs_all_required_rules() -> None:
    evidence = reviewed_evidence()

    product = prepare_published_product(
        product=publishable_draft(),
        evidence=evidence,
    )

    evaluation = evaluate_candidate(
        product=product,
        evidence=evidence,
        requirements=confirmed_requirements(),
    )

    states = {
        check.rule_id: check.state.value
        for check in evaluation.checks
    }

    # The emitted rule set must track the formal gate exactly: wiring a new
    # check without extending DEFAULT_REQUIRED_RULE_IDS (or the reverse) is a
    # regression that this assertion catches against the shared constant.
    assert set(states) == set(DEFAULT_REQUIRED_RULE_IDS)

    assert states["vin.range"] == "PASS"
    assert states["vout.range"] == "PASS"
    assert states["iout.continuous"] == "UNKNOWN"
    assert states["surge.input"] == "PASS"

    # The 3A request fits the 3A continuous rating, but the fixture states
    # no regime for that rating, so the fallback cannot be generalized.
    assert states["iout.peak"] == "UNKNOWN"

    # This fixture has no explicit ambient operating rating.
    assert states["thermal.ambient"] == "UNKNOWN"

    # No structured total-error capability exists, so tolerance is UNKNOWN
    # and can never be replaced by the output-voltage range PASS above.
    assert states["vout.tolerance"] == "UNKNOWN"

    assert evaluation.bucket is CandidateBucket.NEEDS_VERIFICATION


def test_free_text_current_conditions_cannot_grant_qualification() -> None:
    evidence = tuple(
        item.model_copy(
            update={
                "test_conditions": (
                    "VIN=12V, forced airflow, TA=25C, 4-layer PCB only; "
                    "evaluation request uses VIN=18V to 30V, natural "
                    "convection, TA=70C"
                )
            }
        )
        if item.evidence_id == "ev:iout"
        else item
        for item in reviewed_evidence()
    )
    product = prepare_published_product(
        product=publishable_draft().model_copy(
            update={
                "iout_continuous_cooling_method": (
                    ThermalCoolingMode.NATURAL_CONVECTION
                ),
                "iout_continuous_ambient_max_c": Decimal(85),
            }
        ),
        evidence=evidence,
    )

    evaluation = evaluate_candidate(
        product=product,
        evidence=evidence,
        requirements=confirmed_requirements(),
    )
    checks_by_rule = {
        check.rule_id: check
        for check in evaluation.checks
    }
    current_check = checks_by_rule["iout.continuous"]
    peak_check = checks_by_rule["iout.peak"]

    assert current_check.state is CheckState.UNKNOWN
    assert current_check.evidence_ids == ()
    assert (
        "cooling, ambient, VIN, PCB, load, and power"
        in current_check.reason
    )
    assert peak_check.state is CheckState.UNKNOWN
    assert peak_check.evidence_ids == ()
    assert (
        "cooling, ambient, VIN, PCB, load, and power"
        in peak_check.reason
    )


def test_output_tolerance_check_is_bound_to_confirmed_tolerance_requirement() -> None:
    evidence = reviewed_evidence()

    product = prepare_published_product(
        product=publishable_draft(),
        evidence=evidence,
    )

    evaluation = evaluate_candidate(
        product=product,
        evidence=evidence,
        requirements=confirmed_requirements(),
    )

    tolerance_checks = [
        check
        for check in evaluation.checks
        if check.rule_id == "vout.tolerance"
    ]

    assert len(tolerance_checks) == 1

    tolerance_check = tolerance_checks[0]

    assert tolerance_check.field_name == "vout.tolerance"
    assert tolerance_check.state is CheckState.UNKNOWN
    assert "±2" in tolerance_check.requirement

    states = {
        check.rule_id: check.state
        for check in evaluation.checks
    }
    assert states["vout.range"] is CheckState.PASS
    assert states["vout.tolerance"] is CheckState.UNKNOWN
    assert evaluation.bucket is CandidateBucket.NEEDS_VERIFICATION

def ambient_rated_evidence() -> tuple[object, ...]:
    """Reviewed evidence for a product with an explicit 85C ambient rating."""

    source = reviewed_evidence()[0]

    return tuple(reviewed_evidence()) + (
        source.model_copy(
            update={
                "evidence_id": "ev:ambient",
                "field_name": "ambient_temp_max_c",
                "page": 5,
                "section": "Operating Ambient Temperature",
                "excerpt": (
                    "Operating ambient temperature: -40C to 85C "
                    "under natural convection"
                ),
                "limit_kind": LimitKind.RATED_MAX,
            }
        ),
    )


def ambient_rated_product(
    *,
    regime: ThermalCoolingMode | None,
) -> BuckProductRecord:
    """A published product whose 85C ambient rating has a stated regime."""

    draft = publishable_draft().model_copy(
        update={
            "ambient_temp_max_c": Decimal(85),
            "ambient_cooling_method": regime,
            "evidence_ids_by_field": (
                publishable_draft().evidence_ids_by_field
                + (("ambient_temp_max_c", ("ev:ambient",)),)
            ),
        }
    )

    return prepare_published_product(
        product=draft,
        evidence=ambient_rated_evidence(),
    )


def test_thermal_ambient_cannot_pass_without_structured_user_cooling() -> None:
    evidence = ambient_rated_evidence()
    product = ambient_rated_product(
        regime=ThermalCoolingMode.NATURAL_CONVECTION,
    )

    # A numeric 70C request inside an 85C rating still cannot qualify when
    # the user's cooling regime has not been characterized.
    unstated = confirmed_requirements().model_copy(
        update={"cooling_method": None}
    )
    unstated_evaluation = evaluate_candidate(
        product=product,
        evidence=evidence,
        requirements=unstated,
    )
    unstated_states = {
        check.rule_id: check.state
        for check in unstated_evaluation.checks
    }
    assert unstated_states["thermal.ambient"] is CheckState.UNKNOWN
    assert unstated_evaluation.bucket is CandidateBucket.NEEDS_VERIFICATION

    # Matching numbers and a cooling enum still do not prove applicability:
    # PCB construction, heatsink, load, and power conditions are unresolved.
    matched_evaluation = evaluate_candidate(
        product=product,
        evidence=evidence,
        requirements=confirmed_requirements(),
    )
    matched_states = {
        check.rule_id: check
        for check in matched_evaluation.checks
    }
    assert matched_states["thermal.ambient"].state is CheckState.UNKNOWN
    assert matched_states["thermal.ambient"].evidence_ids == ()
    assert (
        "PCB, heatsink, load, and power"
        in matched_states["thermal.ambient"].reason
    )

    # The overall bucket stays NEEDS_VERIFICATION because the tolerance rule
    # is UNKNOWN; thermal evidence cannot substitute for accuracy evidence.
    assert matched_evaluation.bucket is CandidateBucket.NEEDS_VERIFICATION


def test_forced_airflow_rating_never_qualifies_natural_convection() -> None:
    product = ambient_rated_product(
        regime=ThermalCoolingMode.FORCED_AIRFLOW,
    )

    evaluation = evaluate_candidate(
        product=product,
        evidence=ambient_rated_evidence(),
        requirements=confirmed_requirements(),
    )

    states = {
        check.rule_id: check.state
        for check in evaluation.checks
    }

    # 70C is numerically inside the 85C rating, yet the rating was made under
    # forced airflow and cannot prove natural-convection operation.
    assert states["thermal.ambient"] is CheckState.UNKNOWN
    assert evaluation.bucket is CandidateBucket.NEEDS_VERIFICATION


def test_catalog_screening_preserves_near_matches(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog.sqlite3"

    # MP4570 passes electrical checks but lacks an explicit ambient rating,
    # so it should remain NEEDS_VERIFICATION.
    main_evidence = reviewed_evidence()
    main_product = prepare_published_product(
        product=publishable_draft(),
        evidence=main_evidence,
    )

    save_published_catalog(
        database_path=database_path,
        product=main_product,
        evidence=main_evidence,
    )

    # Create a second reviewed product whose VIN maximum is only 24 V.
    # For an 18-30 V requirement it must be retained as NEAR_MATCH,
    # not disappear before deterministic evaluation.
    id_map = {
        "ev:vin": "ev:near24:vin",
        "ev:vout": "ev:near24:vout",
        "ev:iout": "ev:near24:iout",
    }

    near_draft = publishable_draft().model_copy(
        update={
            "product_id": "MPS-NEAR24",
            "base_part_number": "NEAR24",
            "orderable_part_numbers": ("NEAR24",),
            "vin_max_v": Decimal(24),
            "evidence_ids_by_field": (
                ("vin_min_v", ("ev:near24:vin",)),
                ("vin_max_v", ("ev:near24:vin",)),
                ("vout_min_v", ("ev:near24:vout",)),
                ("vout_max_vin_ratio", ("ev:near24:vout",)),
                ("iout_continuous_max_a", ("ev:near24:iout",)),
            ),
        }
    )

    near_evidence = tuple(
        item.model_copy(
            update={
                "evidence_id": id_map[item.evidence_id],
                "product_id": "MPS-NEAR24",
                "excerpt": (
                    "Supply Voltage VIN: 4.5V to 24V"
                    if item.field_name == "vin.range"
                    else item.excerpt
                ),
            }
        )
        for item in reviewed_evidence()
    )

    near_product = prepare_published_product(
        product=near_draft,
        evidence=near_evidence,
    )

    save_published_catalog(
        database_path=database_path,
        product=near_product,
        evidence=near_evidence,
    )

    result = screen_published_catalog(
        database_path=database_path,
        knowledge_base_version="kb-dev-v1",
        requirements=confirmed_requirements(),
    )

    assert result.formal == ()

    assert tuple(
        item.product_id
        for item in result.near_match
    ) == ("MPS-NEAR24",)

    assert tuple(
        item.product_id
        for item in result.needs_verification
    ) == ("MPS-MP4570",)


def test_catalog_screening_keeps_product_and_evidence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog.sqlite3"

    evidence = reviewed_evidence()
    product = prepare_published_product(
        product=publishable_draft(),
        evidence=evidence,
    )

    save_published_catalog(
        database_path=database_path,
        product=product,
        evidence=evidence,
    )

    result = screen_published_catalog(
        database_path=database_path,
        knowledge_base_version="kb-dev-v1",
        requirements=confirmed_requirements(),
    )

    assert len(result.needs_verification) == 1

    candidate = result.needs_verification[0]

    assert candidate.product == product
    assert candidate.evaluation.product_id == product.product_id
    assert candidate.evaluation.bucket is CandidateBucket.NEEDS_VERIFICATION

    assert tuple(
        item.evidence_id
        for item in candidate.evidence
    ) == (
        "ev:iout",
        "ev:vin",
        "ev:vout",
    )
