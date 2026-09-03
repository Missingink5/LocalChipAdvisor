"""JSON persistence for local draft product catalogs."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from local_chip_advisor.domain import EvidenceRef
from local_chip_advisor.domain.product import BuckProductRecord


def save_draft_catalog(
    *,
    directory: str | Path,
    product: BuckProductRecord,
    evidence: Iterable[EvidenceRef],
) -> None:
    """Persist one draft product and its evidence as readable JSON."""

    draft_dir = Path(directory)
    draft_dir.mkdir(parents=True, exist_ok=True)

    evidence_tuple = tuple(evidence)

    product_path = draft_dir / "product.json"
    evidence_path = draft_dir / "evidence.json"

    product_payload = product.model_dump(
        mode="json",
        exclude_none=False,
    )

    evidence_payload = [
        item.model_dump(
            mode="json",
            exclude_none=False,
        )
        for item in evidence_tuple
    ]

    product_path.write_text(
        json.dumps(
            product_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    evidence_path.write_text(
        json.dumps(
            evidence_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def load_draft_catalog(
    directory: str | Path,
) -> tuple[BuckProductRecord, tuple[EvidenceRef, ...]]:
    """Load one draft product and its evidence from JSON."""

    draft_dir = Path(directory)

    product_path = draft_dir / "product.json"
    evidence_path = draft_dir / "evidence.json"

    if not product_path.is_file():
        raise FileNotFoundError(product_path)

    if not evidence_path.is_file():
        raise FileNotFoundError(evidence_path)

    product_data = json.loads(
        product_path.read_text(encoding="utf-8-sig")
    )

    evidence_data = json.loads(
        evidence_path.read_text(encoding="utf-8-sig")
    )

    if not isinstance(evidence_data, list):
        raise ValueError("evidence.json must contain a JSON array")

    product = BuckProductRecord.model_validate(product_data)

    evidence = tuple(
        EvidenceRef.model_validate(item)
        for item in evidence_data
    )

    return product, evidence
