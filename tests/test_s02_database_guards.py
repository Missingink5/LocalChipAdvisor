"""S02 persistence guards; all databases are disposable test fixtures."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from test_sqlite_catalog import published_product, reviewed_evidence

from local_chip_advisor.catalog.sqlite_migrations import migrate_catalog_schema
from local_chip_advisor.catalog.sqlite_store import save_published_catalog


def save(path: Path) -> None:
    save_published_catalog(
        database_path=path, product=published_product(), evidence=reviewed_evidence()
    )


@pytest.mark.parametrize("damage", ["future", "missing"])
def test_save_rejects_existing_unsupported_database(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "catalog.db"
    save(path)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA user_version=999" if damage == "future" else "DROP TABLE evidence")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save(path)
    assert path.read_bytes() == before


def test_product_content_change_requires_new_version(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    save(path)
    before = path.read_bytes()
    changed = published_product().model_copy(update={"manufacturer": "Changed"})
    with pytest.raises(ValueError, match="product conflict"):
        save_published_catalog(database_path=path, product=changed, evidence=reviewed_evidence())
    assert path.read_bytes() == before


def test_migration_rejects_missing_not_null(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    save(path)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute(
            "UPDATE sqlite_schema SET sql=replace(sql, 'TEXT NOT NULL', 'TEXT') WHERE name='products'"
        )
        conn.execute("PRAGMA writable_schema=OFF")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        migrate_catalog_schema(path, dry_run=True)
    assert path.read_bytes() == before


def test_saving_legacy_does_not_migrate(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    save(path)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA user_version=0")
    save(path)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


def test_database_connections_close_and_new_catalog_is_versioned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from local_chip_advisor.catalog.sqlite_store import list_published_products

    opened: list[sqlite3.Connection] = []
    original_connect = sqlite3.connect

    def tracking_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    path = tmp_path / "catalog.db"
    save(path)
    assert migrate_catalog_schema(path, dry_run=True).from_version == 1
    list_published_products(database_path=path, knowledge_base_version="kb-test-v1")
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
