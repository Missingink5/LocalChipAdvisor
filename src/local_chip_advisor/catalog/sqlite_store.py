"""SQLite persistence for published product catalogs."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from local_chip_advisor.domain import EvidenceRef, PublicationStatus
from local_chip_advisor.domain.product import BuckProductRecord


def _connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT NOT NULL,
            knowledge_base_version TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (product_id, knowledge_base_version)
        );

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            knowledge_base_version TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (evidence_id, knowledge_base_version),
            FOREIGN KEY (product_id, knowledge_base_version)
                REFERENCES products (product_id, knowledge_base_version)
                ON DELETE CASCADE
        );
        """
    )


def save_published_catalog(
    *,
    database_path: str | Path,
    product: BuckProductRecord,
    evidence: Iterable[EvidenceRef],
) -> None:
    """Persist one published product and its reviewed evidence atomically."""

    if product.publication_status is not PublicationStatus.PUBLISHED:
        raise ValueError(
            "only PUBLISHED products may enter the published SQLite catalog"
        )

    evidence_items = tuple(evidence)

    bound_evidence_ids = {
        evidence_id
        for _, evidence_ids in product.evidence_ids_by_field
        for evidence_id in evidence_ids
    }

    supplied_evidence_ids = {
        item.evidence_id
        for item in evidence_items
    }

    missing_evidence_ids = (
        bound_evidence_ids - supplied_evidence_ids
    )

    if missing_evidence_ids:
        missing = ", ".join(sorted(missing_evidence_ids))
        raise ValueError(
            f"missing bound evidence: {missing}"
        )

    for item in evidence_items:
        if not item.reviewed:
            raise ValueError(
                f"published evidence must be reviewed: {item.evidence_id}"
            )

        if item.product_id != product.product_id:
            raise ValueError(
                f"evidence belongs to another product: {item.evidence_id}"
            )

        if item.knowledge_base_version != product.knowledge_base_version:
            raise ValueError(
                f"evidence belongs to another knowledge-base version: "
                f"{item.evidence_id}"
            )

    product_json = json.dumps(
        product.model_dump(mode="json", exclude_none=False),
        ensure_ascii=False,
        sort_keys=True,
    )

    with _connect(database_path) as connection:
        _initialize_schema(connection)

        connection.execute(
            """
            INSERT OR REPLACE INTO products (
                product_id,
                knowledge_base_version,
                payload_json
            )
            VALUES (?, ?, ?)
            """,
            (
                product.product_id,
                product.knowledge_base_version,
                product_json,
            ),
        )

        connection.execute(
            """
            DELETE FROM evidence
            WHERE product_id = ?
              AND knowledge_base_version = ?
            """,
            (
                product.product_id,
                product.knowledge_base_version,
            ),
        )

        for item in evidence_items:
            evidence_json = json.dumps(
                item.model_dump(mode="json", exclude_none=False),
                ensure_ascii=False,
                sort_keys=True,
            )

            connection.execute(
                """
                INSERT INTO evidence (
                    evidence_id,
                    product_id,
                    knowledge_base_version,
                    payload_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    item.evidence_id,
                    item.product_id,
                    item.knowledge_base_version,
                    evidence_json,
                ),
            )


def load_published_catalog(
    *,
    database_path: str | Path,
    product_id: str,
    knowledge_base_version: str,
) -> tuple[BuckProductRecord, tuple[EvidenceRef, ...]]:
    """Load one published product and its evidence."""

    path = Path(database_path)

    if not path.is_file():
        raise FileNotFoundError(path)

    with _connect(path) as connection:
        _initialize_schema(connection)

        product_row = connection.execute(
            """
            SELECT payload_json
            FROM products
            WHERE product_id = ?
              AND knowledge_base_version = ?
            """,
            (
                product_id,
                knowledge_base_version,
            ),
        ).fetchone()

        if product_row is None:
            raise KeyError(
                f"published product not found: "
                f"{product_id}@{knowledge_base_version}"
            )

        evidence_rows = connection.execute(
            """
            SELECT payload_json
            FROM evidence
            WHERE product_id = ?
              AND knowledge_base_version = ?
            ORDER BY evidence_id
            """,
            (
                product_id,
                knowledge_base_version,
            ),
        ).fetchall()

    product = BuckProductRecord.model_validate(
        json.loads(product_row[0])
    )

    evidence = tuple(
        EvidenceRef.model_validate(json.loads(row[0]))
        for row in evidence_rows
    )

    return product, evidence
