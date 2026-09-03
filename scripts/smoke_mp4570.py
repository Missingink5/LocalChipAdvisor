"""Real MP4570 evidence-bound smoke test loaded from the local draft catalog."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from local_chip_advisor.catalog.io import load_draft_catalog
from local_chip_advisor.domain import (
    SurgeKnowledge,
    classify_candidate,
    validate_evidence_bindings,
)
from local_chip_advisor.domain.product_rules import (
    check_continuous_output_current,
    check_input_surge,
    check_input_voltage,
    check_output_voltage,
    check_peak_output_current,
    check_ambient_thermal,
)
from local_chip_advisor.ingestion import parse_pdf


ROOT = Path(__file__).resolve().parents[1]

raw_dir = ROOT / "data" / "raw" / "mps" / "MP4570"
draft_dir = ROOT / "data" / "catalog" / "drafts" / "MP4570"

pdf_path = raw_dir / "MP4570_Datasheet.pdf"
manifest_path = raw_dir / "source.json"


# Load persisted structured product data and evidence.
product, evidence_items = load_draft_catalog(draft_dir)
evidence = {
    item.evidence_id: item
    for item in evidence_items
}


# Re-check that the catalog still points to the exact local official PDF.
manifest = json.loads(
    manifest_path.read_text(encoding="utf-8-sig")
)
parsed = parse_pdf(pdf_path)

assert parsed.page_count == 22
assert parsed.sha256.upper() == manifest["sha256"].upper()

for item in evidence_items:
    assert item.product_id == product.product_id
    assert item.knowledge_base_version == product.knowledge_base_version
    assert item.sha256 == parsed.sha256
    assert 1 <= item.page <= parsed.page_count


# Example engineering requirement for the smoke test:
# 18–30V input, 5V output, 2.5A continuous load.
checks = (
    check_input_voltage(
        product=product,
        operating_vin_min_v=Decimal("18"),
        operating_vin_max_v=Decimal("30"),
    ),
    check_output_voltage(
        product=product,
        requested_vout_v=Decimal("5"),
        operating_vin_min_v=Decimal("18"),
    ),
    check_continuous_output_current(
        product=product,
        requested_iout_a=Decimal("2.5"),
    ),
    check_input_surge(
        product=product,
        surge_knowledge=SurgeKnowledge.NONE_EXPECTED,
        surge_voltage_v=None,
        surge_duration_ms=None,
    ),
    check_peak_output_current(
        product=product,
        requested_iout_peak_a=Decimal("3"),
        requested_peak_duration_ms=Decimal("10"),
    ),
    check_ambient_thermal(
        product=product,
        ambient_max_c=Decimal("70"),
        thermal_conditions="natural convection; normal PCB mounting",
    ),
)


evaluation = classify_candidate(
    product_id=product.product_id,
    publication_status=product.publication_status,
    checks=checks,
)

validate_evidence_bindings(
    evaluation,
    evidence,
    knowledge_base_version=product.knowledge_base_version,
)


print("PDF SHA256:", parsed.sha256)
print("Product:", product.base_part_number)
print("Catalog evidence:", len(evidence_items))

for check in checks:
    print(
        f"{check.rule_id}: "
        f"{check.state.value} | "
        f"{check.requirement} | "
        f"{check.actual}"
    )

print("Candidate bucket:", evaluation.bucket.value)
