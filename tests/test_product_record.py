"""Contract tests for structured Buck product master data."""

from datetime import date

import pytest
from pydantic import ValidationError

from local_chip_advisor.domain.product import BuckProductRecord
from local_chip_advisor.domain import PublicationStatus


def valid_product(**overrides: object) -> BuckProductRecord:
    values: dict[str, object] = {
        "product_id": "MPS-MP4570",
        "manufacturer": "Monolithic Power Systems (MPS)",
        "base_part_number": "MP4570",
        "orderable_part_numbers": ("MP4570GF-Z",),
        "knowledge_base_version": "kb-dev-v1",
        "publication_status": PublicationStatus.DRAFT,
        "lifecycle_status": "Active",
        "lifecycle_checked_date": date(2026, 9, 3),

        # Recommended operating data used for hard screening
        "vin_min_v": "4.5",
        "vin_max_v": "55",
        "vout_min_v": "0.8",
        "vout_max_v": "52",
        "iout_continuous_max_a": "3",

        # Absolute maximum is stored for warning/risk purposes only
        "vin_absolute_max_v": "60",

        # Thermal / package
        "junction_temp_min_c": "-40",
        "junction_temp_max_c": "125",
        "package": "QFN",

        # Evidence IDs are program-created pointers to EvidenceRef objects
        "evidence_ids_by_field": (
            ("vin_min_v", ("ev:mp4570:vin-range",)),
            ("vin_max_v", ("ev:mp4570:vin-range",)),
            ("iout_continuous_max_a", ("ev:mp4570:iout",)),
        ),
    }
    values.update(overrides)
    return BuckProductRecord.model_validate(values)


def test_valid_draft_product_is_accepted() -> None:
    product = valid_product()

    assert product.product_id == "MPS-MP4570"
    assert product.vin_min_v < product.vin_max_v
    assert product.publication_status is PublicationStatus.DRAFT


def test_recommended_input_range_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="vin_min_v must be <= vin_max_v"):
        valid_product(vin_min_v="55", vin_max_v="4.5")


def test_output_range_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="vout_min_v must be <= vout_max_v"):
        valid_product(vout_min_v="5", vout_max_v="0.8")


def test_absolute_maximum_cannot_be_below_recommended_maximum() -> None:
    with pytest.raises(
        ValidationError,
        match="vin_absolute_max_v cannot be below vin_max_v",
    ):
        valid_product(vin_max_v="55", vin_absolute_max_v="50")


def test_duplicate_field_evidence_binding_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate evidence binding"):
        valid_product(
            evidence_ids_by_field=(
                ("vin_min_v", ("ev:1",)),
                ("vin_min_v", ("ev:2",)),
            )
        )
