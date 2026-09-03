"""Real MP4570 evidence-bound smoke test using the local official Datasheet."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from local_chip_advisor.domain import (
    EvidenceRef,
    LimitKind,
    PublicationStatus,
    classify_candidate,
    validate_evidence_bindings,
)
from local_chip_advisor.domain.product import BuckProductRecord
from local_chip_advisor.domain.product_rules import (
    check_continuous_output_current,
    check_input_voltage,
    check_output_voltage,
)
from local_chip_advisor.ingestion import parse_pdf


ROOT = Path(__file__).resolve().parents[1]

pdf_path = (
    ROOT
    / "data"
    / "raw"
    / "mps"
    / "MP4570"
    / "MP4570_Datasheet.pdf"
)

manifest_path = pdf_path.parent / "source.json"

manifest = json.loads(
    manifest_path.read_text(encoding="utf-8-sig")
)

parsed = parse_pdf(pdf_path)

assert parsed.page_count == 22
assert parsed.sha256.upper() == manifest["sha256"].upper()

page1 = " ".join(parsed.pages[0].text.split())
page4 = " ".join(parsed.pages[3].text.split())

assert "3A continuous output current" in page1
assert "Supply Voltage VIN" in page4
assert "4.5V to 55V" in page4
assert "Output Voltage VOUT" in page4
assert "1V to 0.9·VIN" in page4


kb_version = "kb-dev-v1"
document_id = "mps-mp4570-datasheet-rev1.01"


evidence = {
    "ev:mp4570:vin-range": EvidenceRef(
        evidence_id="ev:mp4570:vin-range",
        product_id="MPS-MP4570",
        field_name="vin.range",
        knowledge_base_version=kb_version,
        document_id=document_id,
        sha256=parsed.sha256,
        document_title="MP4570 Datasheet",
        document_version="Rev. 1.01",
        page=4,
        section="Recommended Operating Conditions",
        excerpt="Supply Voltage VIN: 4.5V to 55V",
        limit_kind=LimitKind.RECOMMENDED_RANGE,
        source_url=manifest["source_url"],
        reviewed=True,
    ),
    "ev:mp4570:vout-range": EvidenceRef(
        evidence_id="ev:mp4570:vout-range",
        product_id="MPS-MP4570",
        field_name="vout.range",
        knowledge_base_version=kb_version,
        document_id=document_id,
        sha256=parsed.sha256,
        document_title="MP4570 Datasheet",
        document_version="Rev. 1.01",
        page=4,
        section="Recommended Operating Conditions",
        excerpt="Output Voltage VOUT: 1V to 0.9·VIN",
        limit_kind=LimitKind.RECOMMENDED_RANGE,
        source_url=manifest["source_url"],
        reviewed=True,
    ),
    "ev:mp4570:iout": EvidenceRef(
        evidence_id="ev:mp4570:iout",
        product_id="MPS-MP4570",
        field_name="iout.continuous",
        knowledge_base_version=kb_version,
        document_id=document_id,
        sha256=parsed.sha256,
        document_title="MP4570 Datasheet",
        document_version="Rev. 1.01",
        page=1,
        section="DESCRIPTION",
        excerpt="It can provide 3A continuous output current.",
        limit_kind=LimitKind.RATED_MAX,
        source_url=manifest["source_url"],
        reviewed=True,
    ),
}


product = BuckProductRecord(
    product_id="MPS-MP4570",
    manufacturer="Monolithic Power Systems (MPS)",
    base_part_number="MP4570",
    orderable_part_numbers=("MP4570GF-Z",),
    knowledge_base_version=kb_version,

    # Still draft: peak current, surge, and thermal screening
    # are not complete yet.
    publication_status=PublicationStatus.DRAFT,

    vin_min_v=Decimal("4.5"),
    vin_max_v=Decimal("55"),

    vout_min_v=Decimal("1"),
    vout_max_v=None,
    vout_max_vin_ratio=Decimal("0.9"),

    iout_continuous_max_a=Decimal("3"),

    vin_absolute_max_v=Decimal("60"),

    junction_temp_min_c=Decimal("-40"),
    junction_temp_max_c=Decimal("125"),

    package="TSSOP-20 EP",

    evidence_ids_by_field=(
        ("vin_min_v", ("ev:mp4570:vin-range",)),
        ("vin_max_v", ("ev:mp4570:vin-range",)),
        ("vout_min_v", ("ev:mp4570:vout-range",)),
        ("vout_max_vin_ratio", ("ev:mp4570:vout-range",)),
        ("iout_continuous_max_a", ("ev:mp4570:iout",)),
    ),
)


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
)


evaluation = classify_candidate(
    product_id=product.product_id,
    publication_status=product.publication_status,
    checks=checks,
)

validate_evidence_bindings(
    evaluation,
    evidence,
    knowledge_base_version=kb_version,
)


print("PDF SHA256:", parsed.sha256)
print("Product:", product.base_part_number)

for check in checks:
    print(
        f"{check.rule_id}: "
        f"{check.state.value} | "
        f"{check.requirement} | "
        f"{check.actual}"
    )

print("Candidate bucket:", evaluation.bucket.value)
