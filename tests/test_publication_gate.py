"""Publication gate for promoting reviewed draft product records."""

import pytest

from local_chip_advisor.catalog.sqlite_store import (
    load_published_catalog,
    save_published_catalog,
)

from local_chip_advisor.catalog.publication import (
    PublicationGateError,
    prepare_published_product,
)
from local_chip_advisor.domain import EvidenceRef, LimitKind, PublicationStatus
from test_product_record import valid_product


def reviewed_evidence() -> tuple[EvidenceRef, ...]:
    common = {
        "product_id": "MPS-MP4570",
        "knowledge_base_version": "kb-dev-v1",
        "document_id": "mps-mp4570-datasheet-rev1.01",
        "sha256": "a" * 64,
        "document_title": "MP4570 Datasheet",
        "document_version": "Rev. 1.01",
        "source_url": "https://www.monolithicpower.com/example",
        "reviewed": True,
    }

    return (
        EvidenceRef(
            evidence_id="ev:vin",
            field_name="vin.range",
            page=4,
            section="Recommended Operating Conditions",
            excerpt="Supply Voltage VIN: 4.5V to 55V",
            limit_kind=LimitKind.RECOMMENDED_RANGE,
            **common,
        ),
        EvidenceRef(
            evidence_id="ev:vout",
            field_name="vout.range",
            page=4,
            section="Recommended Operating Conditions",
            excerpt="Output Voltage VOUT: 1V to 0.9 VIN",
            limit_kind=LimitKind.RECOMMENDED_RANGE,
            **common,
        ),
        EvidenceRef(
            evidence_id="ev:iout",
            field_name="iout.continuous",
            page=1,
            section="DESCRIPTION",
            excerpt="It can provide 3A continuous output current.",
            limit_kind=LimitKind.RATED_MAX,
            **common,
        ),
    )


def publishable_draft():
    return valid_product(
        publication_status=PublicationStatus.DRAFT,
        vout_min_v="1",
        vout_max_v=None,
        vout_max_vin_ratio="0.9",
        evidence_ids_by_field=(
            ("vin_min_v", ("ev:vin",)),
            ("vin_max_v", ("ev:vin",)),
            ("vout_min_v", ("ev:vout",)),
            ("vout_max_vin_ratio", ("ev:vout",)),
            ("iout_continuous_max_a", ("ev:iout",)),
        ),
    )


def test_reviewed_draft_can_be_prepared_for_publication() -> None:
    draft = publishable_draft()

    published = prepare_published_product(
        product=draft,
        evidence=reviewed_evidence(),
    )

    assert draft.publication_status is PublicationStatus.DRAFT
    assert published.publication_status is PublicationStatus.PUBLISHED
    assert published.product_id == draft.product_id
    assert published.evidence_ids_by_field == draft.evidence_ids_by_field


def test_missing_core_field_evidence_blocks_publication() -> None:
    draft = valid_product(
        publication_status=PublicationStatus.DRAFT,
        vout_min_v="1",
        vout_max_v=None,
        vout_max_vin_ratio="0.9",
        evidence_ids_by_field=(
            ("vin_min_v", ("ev:vin",)),
            ("vin_max_v", ("ev:vin",)),
            ("vout_min_v", ("ev:vout",)),
            ("iout_continuous_max_a", ("ev:iout",)),
        ),
    )

    with pytest.raises(
        PublicationGateError,
        match="vout_max_vin_ratio",
    ):
        prepare_published_product(
            product=draft,
            evidence=reviewed_evidence(),
        )

def test_draft_can_pass_gate_and_round_trip_through_published_sqlite(
    tmp_path,
) -> None:
    draft = publishable_draft()
    evidence = reviewed_evidence()

    published = prepare_published_product(
        product=draft,
        evidence=evidence,
    )

    database_path = tmp_path / "catalog.sqlite3"

    save_published_catalog(
        database_path=database_path,
        product=published,
        evidence=evidence,
    )

    loaded_product, loaded_evidence = load_published_catalog(
        database_path=database_path,
        product_id=published.product_id,
        knowledge_base_version=published.knowledge_base_version,
    )

    assert draft.publication_status is PublicationStatus.DRAFT
    assert published.publication_status is PublicationStatus.PUBLISHED
    assert loaded_product == published
    assert loaded_evidence == tuple(sorted(
        evidence,
        key=lambda item: item.evidence_id,
    ))
