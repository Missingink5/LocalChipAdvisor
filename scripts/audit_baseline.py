"""Read-only baseline audit for the LocalChipAdvisor catalog."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


REQUIRED_TABLES = {
    "products",
    "evidence",
}


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)

    resolved = database_path.resolve(strict=True)
    database_uri = f"{resolved.as_uri()}?mode=ro"

    connection = sqlite3.connect(
        database_uri,
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    return connection


def _load_payload(
    raw_payload: str,
    *,
    label: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON payload for {label}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"payload for {label} is not a JSON object"
        )

    return payload


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _extract_bound_evidence(
    payload: dict[str, Any],
    *,
    label: str,
) -> tuple[tuple[str, str], ...]:
    raw_bindings = payload.get(
        "evidence_ids_by_field",
        [],
    )

    if not isinstance(raw_bindings, list):
        raise ValueError(
            f"invalid evidence_ids_by_field for {label}"
        )

    bindings: list[tuple[str, str]] = []

    for raw_binding in raw_bindings:
        if (
            not isinstance(raw_binding, list)
            or len(raw_binding) != 2
        ):
            raise ValueError(
                f"invalid evidence binding for {label}"
            )

        field_name, raw_evidence_ids = raw_binding

        if not isinstance(field_name, str):
            raise ValueError(
                f"invalid evidence field name for {label}"
            )

        if not isinstance(raw_evidence_ids, list):
            raise ValueError(
                f"invalid evidence ID list for {label}"
            )

        for evidence_id in raw_evidence_ids:
            if not isinstance(evidence_id, str):
                raise ValueError(
                    f"invalid evidence ID for {label}"
                )

            bindings.append(
                (
                    field_name,
                    evidence_id,
                )
            )

    return tuple(bindings)


def audit_database(database_path: Path) -> int:
    problems: list[str] = []

    with _connect_read_only(database_path) as connection:
        user_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        table_rows = connection.execute(
            """
            SELECT name
            FROM sqlite_schema
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        table_names = tuple(
            row["name"]
            for row in table_rows
        )
        table_set = set(table_names)

        print(f"DATABASE: {database_path.resolve()}")
        print(f"USER_VERSION: {user_version}")
        print(
            "TABLES: "
            + (
                ", ".join(table_names)
                if table_names
                else "none"
            )
        )

        missing_tables = sorted(
            REQUIRED_TABLES - table_set
        )

        if missing_tables:
            problems.append(
                "missing required tables: "
                + ", ".join(missing_tables)
            )

        for table_name in table_names:
            quoted = _quote_identifier(table_name)
            row_count = connection.execute(
                f"SELECT COUNT(*) FROM {quoted}"
            ).fetchone()[0]

            print(
                f"ROW_COUNT {table_name}={row_count}"
            )

        integrity_rows = connection.execute(
            "PRAGMA integrity_check"
        ).fetchall()

        integrity_results = tuple(
            str(row[0])
            for row in integrity_rows
        )

        print(
            "INTEGRITY_CHECK: "
            + ", ".join(integrity_results)
        )

        if integrity_results != ("ok",):
            problems.append(
                "integrity_check did not return ok"
            )

        foreign_key_rows = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        print(
            "FOREIGN_KEY_VIOLATIONS: "
            f"{len(foreign_key_rows)}"
        )

        for row in foreign_key_rows:
            print(
                "FOREIGN_KEY_VIOLATION: "
                f"{tuple(row)}"
            )

        if foreign_key_rows:
            problems.append(
                "foreign-key violations detected"
            )

        product_payloads: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}

        if "products" in table_set:
            product_rows = connection.execute(
                """
                SELECT
                    product_id,
                    knowledge_base_version,
                    payload_json
                FROM products
                ORDER BY
                    knowledge_base_version,
                    product_id
                """
            ).fetchall()

            for row in product_rows:
                product_id = row["product_id"]
                knowledge_base_version = (
                    row["knowledge_base_version"]
                )

                label = (
                    f"{product_id}@"
                    f"{knowledge_base_version}"
                )

                payload = _load_payload(
                    row["payload_json"],
                    label=label,
                )

                product_payloads[
                    (
                        product_id,
                        knowledge_base_version,
                    )
                ] = payload

                bound_evidence = (
                    _extract_bound_evidence(
                        payload,
                        label=label,
                    )
                )

                publication_status = payload.get(
                    "publication_status",
                    "<missing>",
                )

                print(
                    "PRODUCT: "
                    f"{label} "
                    f"publication_status="
                    f"{publication_status} "
                    f"bound_evidence="
                    f"{len(bound_evidence)}"
                )

        evidence_keys: set[
            tuple[str, str]
        ] = set()

        reviewed_count = 0
        evidence_count = 0

        if "evidence" in table_set:
            evidence_rows = connection.execute(
                """
                SELECT
                    evidence_id,
                    product_id,
                    knowledge_base_version,
                    payload_json
                FROM evidence
                ORDER BY
                    knowledge_base_version,
                    evidence_id
                """
            ).fetchall()

            evidence_count = len(evidence_rows)

            for row in evidence_rows:
                evidence_id = row["evidence_id"]
                product_id = row["product_id"]
                knowledge_base_version = (
                    row["knowledge_base_version"]
                )

                label = (
                    f"{evidence_id}@"
                    f"{knowledge_base_version}"
                )

                payload = _load_payload(
                    row["payload_json"],
                    label=label,
                )

                reviewed = payload.get(
                    "reviewed",
                    "<missing>",
                )

                if reviewed is True:
                    reviewed_count += 1

                evidence_keys.add(
                    (
                        evidence_id,
                        knowledge_base_version,
                    )
                )

                print(
                    "EVIDENCE: "
                    f"{label} "
                    f"product_id={product_id} "
                    f"reviewed={reviewed} "
                    f"field_name="
                    f"{payload.get('field_name', '<missing>')} "
                    f"document_version="
                    f"{payload.get('document_version', '<missing>')} "
                    f"page="
                    f"{payload.get('page', '<missing>')}"
                )

        print(
            "EVIDENCE_REVIEWED: "
            f"{reviewed_count}/{evidence_count}"
        )

        missing_bindings: list[str] = []

        for (
            product_id,
            knowledge_base_version,
        ), payload in product_payloads.items():
            label = (
                f"{product_id}@"
                f"{knowledge_base_version}"
            )

            for (
                field_name,
                evidence_id,
            ) in _extract_bound_evidence(
                payload,
                label=label,
            ):
                key = (
                    evidence_id,
                    knowledge_base_version,
                )

                if key not in evidence_keys:
                    missing_bindings.append(
                        f"{label} "
                        f"field={field_name} "
                        f"evidence_id={evidence_id}"
                    )

        print(
            "BOUND_EVIDENCE_MISSING: "
            f"{len(missing_bindings)}"
        )

        for missing in missing_bindings:
            print(
                f"BOUND_EVIDENCE_MISSING_ITEM: "
                f"{missing}"
            )

        if missing_bindings:
            problems.append(
                "product evidence bindings are broken"
            )

    if problems:
        print("AUDIT_STATUS: FAILED")

        for problem in problems:
            print(
                f"AUDIT_PROBLEM: {problem}"
            )

        return 1

    print("AUDIT_STATUS: OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit of a LocalChipAdvisor "
            "SQLite catalog."
        )
    )
    parser.add_argument(
        "--database-path",
        required=True,
        type=Path,
        help="Path to the existing catalog SQLite database.",
    )
    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return audit_database(
            args.database_path
        )
    except (
        FileNotFoundError,
        sqlite3.Error,
        ValueError,
    ) as exc:
        print(
            f"AUDIT_ERROR: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
