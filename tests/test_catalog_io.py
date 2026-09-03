"""Contract tests for local draft catalog persistence."""

from decimal import Decimal
from pathlib import Path

from local_chip_advisor.catalog.io import load_draft_catalog, save_draft_catalog
from local_chip_advisor.domain import EvidenceRef, LimitKind, PublicationStatus
from local_chip_advisor.domain.product import BuckProductRecord


def test_draft_catalog_round_trip(tmp_path: Path) -> None:
    product = BuckProductRecord(
        product_id="MPS-MP4570",
        manufacturer="Monolithic Power Systems (MPS)",
        base_part_number="MP4570",
        orderable_part_numbers=("MP4570GF-Z",),
        knowledge_base_version="kb-dev-v1",
        publication_status=PublicationStatus.DRAFT,
        vin_min_v=Decimal("4.5"),
        vin_max_v=Decimal("55"),
        vout_min_v=Decimal("1"),
        vout_max_vin_ratio=Decimal("0.9"),
        iout_continuous_max_a=Decimal("3"),
        evidence_ids_by_field=(
            ("vin_min_v", ("ev:mp4570:vin-range",)),
            ("vin_max_v", ("ev:mp4570:vin-range",)),
        ),
    )

    evidence = (
        EvidenceRef(
            evidence_id="ev:mp4570:vin-range",
            product_id="MPS-MP4570",
            field_name="vin.range",
            knowledge_base_version="kb-dev-v1",
            document_id="mps-mp4570-datasheet-rev1.01",
            sha256="a" * 64,
            document_title="MP4570 Datasheet",
            document_version="Rev. 1.01",
            page=4,
            section="Recommended Operating Conditions",
            excerpt="Supply Voltage VIN: 4.5V to 55V",
            limit_kind=LimitKind.RECOMMENDED_RANGE,
            source_url="https://www.monolithicpower.com/example",
            reviewed=True,
        ),
    )

    draft_dir = tmp_path / "MP4570"

    save_draft_catalog(
        directory=draft_dir,
        product=product,
        evidence=evidence,
    )

    loaded_product, loaded_evidence = load_draft_catalog(draft_dir)

    assert (draft_dir / "product.json").is_file()
    assert (draft_dir / "evidence.json").is_file()
    assert loaded_product == product
    assert loaded_evidence == evidence
