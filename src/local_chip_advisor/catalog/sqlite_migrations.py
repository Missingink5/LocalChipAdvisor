"""Explicit schema migrations for the SQLite catalog."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import cast

CURRENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MigrationReport:
    """Read-only summary of catalog migration state."""

    from_version: int
    to_version: int
    changes: tuple[str, ...]
    legacy_v0_detected: bool
    dry_run: bool
    applied: bool


_LEGACY_V0_COLUMNS = {
    "products": (
        "product_id",
        "knowledge_base_version",
        "vin_min_v",
        "vin_max_v",
        "vout_min_v",
        "vout_max_v",
        "vout_max_vin_ratio",
        "iout_continuous_max_a",
        "payload_json",
    ),
    "evidence": (
        "evidence_id",
        "product_id",
        "knowledge_base_version",
        "payload_json",
    ),
}

_LEGACY_V0_PRIMARY_KEYS = {
    "products": (
        "product_id",
        "knowledge_base_version",
    ),
    "evidence": (
        "evidence_id",
        "knowledge_base_version",
    ),
}

_LEGACY_V0_EVIDENCE_FOREIGN_KEY = (
    (
        0,
        0,
        "products",
        "product_id",
        "product_id",
        "NO ACTION",
        "CASCADE",
        "NONE",
    ),
    (
        0,
        1,
        "products",
        "knowledge_base_version",
        "knowledge_base_version",
        "NO ACTION",
        "CASCADE",
        "NONE",
    ),
)


def _connect_readonly(
    database_path: str | Path,
) -> sqlite3.Connection:
    path = Path(database_path)

    if not path.is_file():
        raise FileNotFoundError(path)

    database_uri = path.resolve(strict=True).as_uri() + "?mode=ro"

    connection = sqlite3.connect(
        database_uri,
        uri=True,
    )
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _connect_writable(
    database_path: str | Path,
) -> sqlite3.Connection:
    path = Path(database_path)

    if not path.is_file():
        raise FileNotFoundError(path)

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_info(
    connection: sqlite3.Connection,
    table_name: str,
) -> tuple[tuple[int, str, str, int, str | None, int], ...]:
    return cast(
        tuple[tuple[int, str, str, int, str | None, int], ...],
        tuple(connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()),
    )


def _table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> tuple[str, ...]:
    return tuple(
        row[1]
        for row in _table_info(
            connection,
            table_name,
        )
    )


def _primary_key_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> tuple[str, ...]:
    primary_key_parts = sorted(
        (
            row[5],
            row[1],
        )
        for row in _table_info(
            connection,
            table_name,
        )
        if row[5] > 0
    )

    return tuple(column_name for _, column_name in primary_key_parts)


def _evidence_foreign_keys(
    connection: sqlite3.Connection,
) -> tuple[tuple[object, ...], ...]:
    return tuple(connection.execute('PRAGMA foreign_key_list("evidence")').fetchall())


def _is_legacy_v0_catalog(
    connection: sqlite3.Connection,
    *,
    allow_extra_tables: bool = False,
) -> bool:
    table_names = {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_schema
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }

    if not set(_LEGACY_V0_COLUMNS).issubset(table_names) or (
        not allow_extra_tables and table_names != set(_LEGACY_V0_COLUMNS)
    ):
        return False

    for table_name in _LEGACY_V0_COLUMNS:
        for row in _table_info(connection, table_name):
            name, declared_type, not_null, default = row[1:5]
            required = name in {
                "product_id",
                "knowledge_base_version",
                "payload_json",
                "evidence_id",
            }
            expected_type = "TEXT" if required else "REAL"
            if (
                declared_type.upper() != expected_type
                or bool(not_null) != required
                or default is not None
            ):
                return False

    columns_match = all(
        _table_columns(connection, table_name) == expected_columns
        for table_name, expected_columns in _LEGACY_V0_COLUMNS.items()
    )

    primary_keys_match = all(
        _primary_key_columns(connection, table_name) == expected_primary_key
        for table_name, expected_primary_key in _LEGACY_V0_PRIMARY_KEYS.items()
    )

    evidence_foreign_key_matches = (
        _evidence_foreign_keys(connection) == _LEGACY_V0_EVIDENCE_FOREIGN_KEY
    )

    return columns_match and primary_keys_match and evidence_foreign_key_matches


def _is_current_catalog_schema(
    connection: sqlite3.Connection,
) -> bool:
    """Validate the structural baseline used by schema version 1."""
    return _is_legacy_v0_catalog(connection)


def migrate_catalog_schema(
    database_path: str | Path,
    *,
    dry_run: bool = False,
) -> MigrationReport:
    """Inspect or explicitly migrate a catalog schema."""
    with closing(_connect_readonly(database_path)) as connection:
        from_version = connection.execute("PRAGMA user_version").fetchone()[0]

        legacy_v0_detected = from_version == 0 and _is_legacy_v0_catalog(connection)

        if from_version == 0 and not legacy_v0_detected:
            raise ValueError("unsupported legacy v0 schema")

        if from_version not in (
            0,
            CURRENT_SCHEMA_VERSION,
        ):
            raise ValueError(f"unsupported catalog schema version: {from_version}")

        if from_version == CURRENT_SCHEMA_VERSION and not _is_current_catalog_schema(connection):
            raise ValueError("unsupported current schema")

        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("catalog integrity check failed")

        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()

        if foreign_key_violations:
            raise ValueError("catalog foreign key violations detected")

    planned_changes = (
        ((f"set user_version from {from_version} to {CURRENT_SCHEMA_VERSION}"),)
        if legacy_v0_detected
        else ()
    )

    report = MigrationReport(
        from_version=from_version,
        to_version=CURRENT_SCHEMA_VERSION,
        changes=planned_changes,
        legacy_v0_detected=legacy_v0_detected,
        dry_run=dry_run,
        applied=False,
    )

    if dry_run:
        return report

    if from_version == CURRENT_SCHEMA_VERSION:
        return report

    with closing(_connect_writable(database_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")

        current_version = connection.execute("PRAGMA user_version").fetchone()[0]

        if current_version != 0:
            raise RuntimeError("catalog schema changed during migration")

        if not _is_legacy_v0_catalog(connection):
            raise ValueError("unsupported legacy v0 schema")

        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("catalog integrity check failed")

        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()

        if foreign_key_violations:
            raise ValueError("catalog foreign key violations detected")

        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

        migrated_version = connection.execute("PRAGMA user_version").fetchone()[0]

        if migrated_version != CURRENT_SCHEMA_VERSION:
            raise RuntimeError("catalog schema version was not activated")

    return MigrationReport(
        from_version=from_version,
        to_version=CURRENT_SCHEMA_VERSION,
        changes=planned_changes,
        legacy_v0_detected=True,
        dry_run=False,
        applied=True,
    )
