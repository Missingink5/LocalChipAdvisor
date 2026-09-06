"""Contract tests for explicit SQLite catalog migrations."""

import sqlite3
from importlib import import_module
from pathlib import Path

import pytest


def test_explicit_catalog_migration_api_exists() -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    assert callable(
        migrations.migrate_catalog_schema
    )


def test_dry_run_recognizes_legacy_v0_without_modifying_database(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "legacy-v0.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE products (
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                vin_min_v REAL,
                vin_max_v REAL,
                vout_min_v REAL,
                vout_max_v REAL,
                vout_max_vin_ratio REAL,
                iout_continuous_max_a REAL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    product_id,
                    knowledge_base_version
                )
            );

            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    evidence_id,
                    knowledge_base_version
                ),
                FOREIGN KEY (
                    product_id,
                    knowledge_base_version
                )
                    REFERENCES products (
                        product_id,
                        knowledge_base_version
                    )
                    ON DELETE CASCADE
            );
            """
        )

        connection.execute(
            """
            INSERT INTO products (
                product_id,
                knowledge_base_version,
                payload_json
            )
            VALUES (?, ?, ?)
            """,
            (
                "MPS-MP4570",
                "kb-dev-v1",
                '{"product_id":"MPS-MP4570"}',
            ),
        )

        for evidence_id in (
            "ev:mp4570:vin-range",
            "ev:mp4570:vout-range",
            "ev:mp4570:iout",
        ):
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
                    evidence_id,
                    "MPS-MP4570",
                    "kb-dev-v1",
                    '{"reviewed":true}',
                ),
            )

    before_bytes = database_path.read_bytes()

    with sqlite3.connect(database_path) as connection:
        before_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        before_product_count = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]
        before_evidence_count = connection.execute(
            "SELECT COUNT(*) FROM evidence"
        ).fetchone()[0]

    assert before_version == 0
    assert before_product_count == 1
    assert before_evidence_count == 3

    report = migrations.migrate_catalog_schema(
        database_path=database_path,
        dry_run=True,
    )

    assert report.from_version == 0
    assert report.legacy_v0_detected is True
    assert report.dry_run is True
    assert report.applied is False

    with sqlite3.connect(database_path) as connection:
        after_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        after_product_count = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]
        after_evidence_count = connection.execute(
            "SELECT COUNT(*) FROM evidence"
        ).fetchone()[0]

    assert after_version == 0
    assert after_product_count == 1
    assert after_evidence_count == 3
    assert database_path.read_bytes() == before_bytes


def test_dry_run_rejects_legacy_v0_with_missing_evidence_foreign_key(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "invalid-legacy-v0.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE products (
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                vin_min_v REAL,
                vin_max_v REAL,
                vout_min_v REAL,
                vout_max_v REAL,
                vout_max_vin_ratio REAL,
                iout_continuous_max_a REAL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    product_id,
                    knowledge_base_version
                )
            );

            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    evidence_id,
                    knowledge_base_version
                )
            );
            """
        )

    before_bytes = database_path.read_bytes()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == 0

        foreign_keys = connection.execute(
            'PRAGMA foreign_key_list("evidence")'
        ).fetchall()

    assert foreign_keys == []

    with pytest.raises(
        ValueError,
        match="unsupported legacy v0 schema",
    ):
        migrations.migrate_catalog_schema(
            database_path=database_path,
            dry_run=True,
        )

    assert database_path.read_bytes() == before_bytes


def test_migrate_legacy_v0_to_versioned_baseline_preserves_data_and_is_idempotent(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "legacy-v0.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE products (
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                vin_min_v REAL,
                vin_max_v REAL,
                vout_min_v REAL,
                vout_max_v REAL,
                vout_max_vin_ratio REAL,
                iout_continuous_max_a REAL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    product_id,
                    knowledge_base_version
                )
            );

            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    evidence_id,
                    knowledge_base_version
                ),
                FOREIGN KEY (
                    product_id,
                    knowledge_base_version
                )
                    REFERENCES products (
                        product_id,
                        knowledge_base_version
                    )
                    ON DELETE CASCADE
            );
            """
        )

        connection.execute(
            """
            INSERT INTO products (
                product_id,
                knowledge_base_version,
                payload_json
            )
            VALUES (?, ?, ?)
            """,
            (
                "MPS-MP4570",
                "kb-dev-v1",
                '{"product_id":"MPS-MP4570"}',
            ),
        )

        for evidence_id in (
            "ev:mp4570:vin-range",
            "ev:mp4570:vout-range",
            "ev:mp4570:iout",
        ):
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
                    evidence_id,
                    "MPS-MP4570",
                    "kb-dev-v1",
                    '{"reviewed":true}',
                ),
            )

    with sqlite3.connect(database_path) as connection:
        before_products = connection.execute(
            """
            SELECT *
            FROM products
            ORDER BY product_id, knowledge_base_version
            """
        ).fetchall()

        before_evidence = connection.execute(
            """
            SELECT *
            FROM evidence
            ORDER BY evidence_id, knowledge_base_version
            """
        ).fetchall()

        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == 0

    first_report = migrations.migrate_catalog_schema(
        database_path=database_path,
    )

    with sqlite3.connect(database_path) as connection:
        first_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        first_products = connection.execute(
            """
            SELECT *
            FROM products
            ORDER BY product_id, knowledge_base_version
            """
        ).fetchall()

        first_evidence = connection.execute(
            """
            SELECT *
            FROM evidence
            ORDER BY evidence_id, knowledge_base_version
            """
        ).fetchall()

        first_integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        first_fk_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert migrations.CURRENT_SCHEMA_VERSION == 1
    assert first_version == migrations.CURRENT_SCHEMA_VERSION
    assert first_products == before_products
    assert first_evidence == before_evidence
    assert first_integrity == "ok"
    assert first_fk_violations == []
    assert first_report.from_version == 0
    assert first_report.applied is True
    assert first_report.dry_run is False

    second_report = migrations.migrate_catalog_schema(
        database_path=database_path,
    )

    with sqlite3.connect(database_path) as connection:
        second_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        second_products = connection.execute(
            """
            SELECT *
            FROM products
            ORDER BY product_id, knowledge_base_version
            """
        ).fetchall()

        second_evidence = connection.execute(
            """
            SELECT *
            FROM evidence
            ORDER BY evidence_id, knowledge_base_version
            """
        ).fetchall()

    assert second_version == migrations.CURRENT_SCHEMA_VERSION
    assert second_products == before_products
    assert second_evidence == before_evidence
    assert second_report.from_version == migrations.CURRENT_SCHEMA_VERSION
    assert second_report.applied is False
    assert second_report.dry_run is False


def test_dry_run_reports_planned_version_change(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "legacy-v0-summary.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE products (
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                vin_min_v REAL,
                vin_max_v REAL,
                vout_min_v REAL,
                vout_max_v REAL,
                vout_max_vin_ratio REAL,
                iout_continuous_max_a REAL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    product_id,
                    knowledge_base_version
                )
            );

            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    evidence_id,
                    knowledge_base_version
                ),
                FOREIGN KEY (
                    product_id,
                    knowledge_base_version
                )
                    REFERENCES products (
                        product_id,
                        knowledge_base_version
                    )
                    ON DELETE CASCADE
            );
            """
        )

    before_bytes = database_path.read_bytes()

    report = migrations.migrate_catalog_schema(
        database_path=database_path,
        dry_run=True,
    )

    assert report.from_version == 0
    assert report.to_version == migrations.CURRENT_SCHEMA_VERSION
    assert report.changes == (
        "set user_version from 0 to 1",
    )
    assert report.dry_run is True
    assert report.applied is False
    assert database_path.read_bytes() == before_bytes


def test_dry_run_rejects_future_schema_version(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "future-schema.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "PRAGMA user_version = 2"
        )

    before_bytes = database_path.read_bytes()

    with pytest.raises(
        ValueError,
        match="unsupported catalog schema version: 2",
    ):
        migrations.migrate_catalog_schema(
            database_path=database_path,
            dry_run=True,
        )

    assert database_path.read_bytes() == before_bytes


def test_migration_rejects_foreign_key_violations_without_activating_version(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "legacy-v0-broken-fk.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE products (
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                vin_min_v REAL,
                vin_max_v REAL,
                vout_min_v REAL,
                vout_max_v REAL,
                vout_max_vin_ratio REAL,
                iout_continuous_max_a REAL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    product_id,
                    knowledge_base_version
                )
            );

            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    evidence_id,
                    knowledge_base_version
                ),
                FOREIGN KEY (
                    product_id,
                    knowledge_base_version
                )
                    REFERENCES products (
                        product_id,
                        knowledge_base_version
                    )
                    ON DELETE CASCADE
            );
            """
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
                "ev:orphan",
                "missing-product",
                "kb-dev-v1",
                '{"reviewed":true}',
            ),
        )

    with sqlite3.connect(database_path) as connection:
        before_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        before_fk_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert before_version == 0
    assert before_fk_violations

    with pytest.raises(
        ValueError,
        match="foreign key violations",
    ):
        migrations.migrate_catalog_schema(
            database_path=database_path,
        )

    with sqlite3.connect(database_path) as connection:
        after_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        after_fk_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert after_version == 0
    assert after_fk_violations == before_fk_violations


def test_dry_run_rejects_foreign_key_violations_without_modifying_database(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "legacy-v0-broken-fk-dry-run.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE products (
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                vin_min_v REAL,
                vin_max_v REAL,
                vout_min_v REAL,
                vout_max_v REAL,
                vout_max_vin_ratio REAL,
                iout_continuous_max_a REAL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    product_id,
                    knowledge_base_version
                )
            );

            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    evidence_id,
                    knowledge_base_version
                ),
                FOREIGN KEY (
                    product_id,
                    knowledge_base_version
                )
                    REFERENCES products (
                        product_id,
                        knowledge_base_version
                    )
                    ON DELETE CASCADE
            );
            """
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
                "ev:orphan-dry-run",
                "missing-product",
                "kb-dev-v1",
                '{"reviewed":true}',
            ),
        )

    before_bytes = database_path.read_bytes()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == 0

        before_fk_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert before_fk_violations

    with pytest.raises(
        ValueError,
        match="foreign key violations",
    ):
        migrations.migrate_catalog_schema(
            database_path=database_path,
            dry_run=True,
        )

    assert database_path.read_bytes() == before_bytes

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == 0

        after_fk_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert after_fk_violations == before_fk_violations


def test_dry_run_rejects_current_version_with_wrong_schema(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "invalid-current-schema.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            f"PRAGMA user_version = {migrations.CURRENT_SCHEMA_VERSION}"
        )

    before_bytes = database_path.read_bytes()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == migrations.CURRENT_SCHEMA_VERSION

        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_schema
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()

    assert tables == []

    with pytest.raises(
        ValueError,
        match="unsupported current schema",
    ):
        migrations.migrate_catalog_schema(
            database_path=database_path,
            dry_run=True,
        )

    assert database_path.read_bytes() == before_bytes


def test_dry_run_rejects_current_schema_with_foreign_key_violations(
    tmp_path: Path,
) -> None:
    migrations = import_module(
        "local_chip_advisor.catalog.sqlite_migrations"
    )

    database_path = tmp_path / "current-v1-broken-fk.sqlite3"

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE products (
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                vin_min_v REAL,
                vin_max_v REAL,
                vout_min_v REAL,
                vout_max_v REAL,
                vout_max_vin_ratio REAL,
                iout_continuous_max_a REAL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    product_id,
                    knowledge_base_version
                )
            );

            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                knowledge_base_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (
                    evidence_id,
                    knowledge_base_version
                ),
                FOREIGN KEY (
                    product_id,
                    knowledge_base_version
                )
                    REFERENCES products (
                        product_id,
                        knowledge_base_version
                    )
                    ON DELETE CASCADE
            );
            """
        )

        connection.execute(
            f"PRAGMA user_version = {migrations.CURRENT_SCHEMA_VERSION}"
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
                "ev:current-orphan",
                "missing-product",
                "kb-dev-v1",
                '{"reviewed":true}',
            ),
        )

    before_bytes = database_path.read_bytes()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == migrations.CURRENT_SCHEMA_VERSION

        before_fk_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert before_fk_violations

    with pytest.raises(
        ValueError,
        match="foreign key violations",
    ):
        migrations.migrate_catalog_schema(
            database_path=database_path,
            dry_run=True,
        )

    assert database_path.read_bytes() == before_bytes
