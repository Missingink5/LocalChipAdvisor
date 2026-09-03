"""Contract tests for the published SQLite product catalog."""

from decimal import Decimal
from pathlib import Path

import pytest

from local_chip_advisor.catalog.sqlite_store import (
    load_published_catalog,
    save_published_catalog,
)
from local_chip_advisor.domain import EvidenceRef, LimitKind, PublicationStatus
from local_chip_advisor.domain.product import BuckProductRecord


def published_product(
    *,
    publication_status: PublicationStatus = PublicationStatus.PUBLISHED,
) -> BuckProductRecord:
    return BuckProductRecord(
        product_id="MPS-MP4570",
        manufacturer="Monolithic Power Systems (MPS)",
        base_part_number="MP4570",
        orderable_part_numbers=("MP4570GF-Z",),
        knowledge_base_version="kb-test-v1",
        publication_status=publication_status,
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


def reviewed_evidence() -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            evidence_id="ev:mp4570:vin-range",
            product_id="MPS-MP4570",
            field_name="vin.range",
            knowledge_base_version="kb-test-v1",
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


def test_published_sqlite_catalog_round_trip(tmp_path: Path) -> None:
    database_path = tmp_path / "catalog.sqlite3"

    product = published_product()
    evidence = reviewed_evidence()

    save_published_catalog(
        database_path=database_path,
        product=product,
        evidence=evidence,
    )

    loaded_product, loaded_evidence = load_published_catalog(
        database_path=database_path,
        product_id="MPS-MP4570",
        knowledge_base_version="kb-test-v1",
    )

    assert database_path.is_file()
    assert loaded_product == product
    assert loaded_evidence == evidence


def test_draft_product_cannot_enter_published_sqlite_catalog(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog.sqlite3"

    with pytest.raises(ValueError, match="PUBLISHED"):
        save_published_catalog(
            database_path=database_path,
            product=published_product(
                publication_status=PublicationStatus.DRAFT,
            ),
            evidence=reviewed_evidence(),
        )


def test_published_product_rejects_missing_bound_evidence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog.sqlite3"

    product = published_product()

    with pytest.raises(ValueError, match="missing bound evidence"):
        save_published_catalog(
            database_path=database_path,
            product=product,
            evidence=(),
        )
