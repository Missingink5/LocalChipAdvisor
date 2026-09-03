"""Application-level deterministic candidate screening."""

from decimal import Decimal
from pathlib import Path

from local_chip_advisor.catalog.publication import prepare_published_product
from local_chip_advisor.catalog.sqlite_store import save_published_catalog
from local_chip_advisor.domain import (
    CandidateBucket,
    RequirementCard,
    SurgeKnowledge,
)
from local_chip_advisor.screening import (
    evaluate_candidate,
    screen_published_catalog,
)
from test_publication_gate import publishable_draft, reviewed_evidence


def confirmed_requirements() -> RequirementCard:
    return RequirementCard(
        raw_request="18-30V input, 5V output, 2.5A continuous, 3A peak for 10ms",
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
        thermal_conditions="natural convection; normal PCB mounting",
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

    assert set(states) == {
        "vin.range",
        "vout.range",
        "iout.continuous",
        "iout.peak",
        "surge.input",
        "thermal.ambient",
    }

    assert states["vin.range"] == "PASS"
    assert states["vout.range"] == "PASS"
    assert states["iout.continuous"] == "PASS"
    assert states["iout.peak"] == "PASS"
    assert states["surge.input"] == "PASS"

    # This fixture has no explicit ambient operating rating.
    assert states["thermal.ambient"] == "UNKNOWN"

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
            "vin_max_v": Decimal("24"),
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
