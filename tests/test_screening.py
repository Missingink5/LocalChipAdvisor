"""Application-level deterministic candidate screening."""

from decimal import Decimal

from local_chip_advisor.catalog.publication import prepare_published_product
from local_chip_advisor.domain import (
    CandidateBucket,
    RequirementCard,
    SurgeKnowledge,
)
from local_chip_advisor.screening import evaluate_candidate
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
