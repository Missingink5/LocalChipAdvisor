"""Gate for promoting reviewed draft product records to PUBLISHED."""

from __future__ import annotations

from collections.abc import Iterable

from local_chip_advisor.domain import (
    EvidenceRef,
    LimitKind,
    PublicationStatus,
)
from local_chip_advisor.domain.product import BuckProductRecord


class PublicationGateError(ValueError):
    """Raised when a draft product is not safe to publish."""


DECISIVE_LIMIT_KINDS = {
    LimitKind.RECOMMENDED_RANGE,
    LimitKind.GUARANTEED_MIN,
    LimitKind.GUARANTEED_MAX,
    LimitKind.RATED_MAX,
}


EXPECTED_EVIDENCE_FIELDS = {
    "vin_min_v": "vin.range",
    "vin_max_v": "vin.range",
    "vout_min_v": "vout.range",
    "vout_max_v": "vout.range",
    "vout_max_vin_ratio": "vout.range",
    "iout_continuous_max_a": "iout.continuous",
}


def _require_reviewed_evidence(
    *,
    product: BuckProductRecord,
    evidence_by_id: dict[str, EvidenceRef],
    product_field: str,
) -> None:
    evidence_ids = product.evidence_ids_for(product_field)

    if not evidence_ids:
        raise PublicationGateError(
            f"missing reviewed evidence binding for {product_field}"
        )

    expected_field = EXPECTED_EVIDENCE_FIELDS[product_field]

    for evidence_id in evidence_ids:
        item = evidence_by_id.get(evidence_id)

        if item is None:
            raise PublicationGateError(
                f"missing evidence object for {product_field}: "
                f"{evidence_id}"
            )

        if item.product_id != product.product_id:
            raise PublicationGateError(
                f"evidence belongs to another product: {evidence_id}"
            )

        if item.knowledge_base_version != product.knowledge_base_version:
            raise PublicationGateError(
                f"evidence belongs to another knowledge-base version: "
                f"{evidence_id}"
            )

        if not item.reviewed:
            raise PublicationGateError(
                f"evidence has not been reviewed: {evidence_id}"
            )

        if item.field_name != expected_field:
            raise PublicationGateError(
                f"evidence field mismatch for {product_field}: "
                f"{evidence_id}"
            )

        if item.limit_kind not in DECISIVE_LIMIT_KINDS:
            raise PublicationGateError(
                f"non-decisive evidence cannot publish {product_field}: "
                f"{evidence_id}"
            )


def prepare_published_product(
    *,
    product: BuckProductRecord,
    evidence: Iterable[EvidenceRef],
) -> BuckProductRecord:
    """Validate a reviewed draft and return an immutable PUBLISHED copy."""

    if product.publication_status is not PublicationStatus.DRAFT:
        raise PublicationGateError(
            "only DRAFT products may be prepared for publication"
        )

    required_fields = (
        "vin_min_v",
        "vin_max_v",
        "vout_min_v",
        "iout_continuous_max_a",
    )

    for field_name in required_fields:
        if getattr(product, field_name) is None:
            raise PublicationGateError(
                f"missing required publication field: {field_name}"
            )

    if (
        product.vout_max_v is None
        and product.vout_max_vin_ratio is None
    ):
        raise PublicationGateError(
            "missing required publication field: "
            "vout_max_v or vout_max_vin_ratio"
        )

    evidence_items = tuple(evidence)
    evidence_by_id = {
        item.evidence_id: item
        for item in evidence_items
    }

    if len(evidence_by_id) != len(evidence_items):
        raise PublicationGateError("duplicate evidence_id supplied")

    for field_name in required_fields:
        _require_reviewed_evidence(
            product=product,
            evidence_by_id=evidence_by_id,
            product_field=field_name,
        )

    output_upper_fields = tuple(
        field_name
        for field_name in (
            "vout_max_v",
            "vout_max_vin_ratio",
        )
        if getattr(product, field_name) is not None
    )

    for field_name in output_upper_fields:
        _require_reviewed_evidence(
            product=product,
            evidence_by_id=evidence_by_id,
            product_field=field_name,
        )

    return product.model_copy(
        update={
            "publication_status": PublicationStatus.PUBLISHED,
        }
    )
