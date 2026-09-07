"""SQLite persistence for the local knowledge repository.

The knowledge database is a separate file from the published product
catalog; the two stores have no foreign keys and must not be joined. This
module follows the S02/B07/B08 safety conventions:

- read connections use ``mode=ro`` + ``query_only`` and never create files;
- write connections own schema initialisation and ``user_version``;
- ``INSERT OR REPLACE`` is forbidden; saves use ``ON CONFLICT ... DO UPDATE``;
- same id with different content raises an explicit ``KnowledgeConflict``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path

from .models import (
    ChunkLinkRecord,
    ChunkLinkKind,
    ChunkRecord,
    DocumentProductLink,
    DocumentRecord,
    KNOWLEDGE_SCHEMA_VERSION,
    PageRecord,
    SegmentRecord,
    SnapshotRecord,
)


class KnowledgeError(RuntimeError):
    """Base class for knowledge-repository failures."""


class KnowledgeSchemaError(KnowledgeError):
    """The on-disk schema does not match the current S05 expectations."""


class KnowledgeConflict(KnowledgeError):
    """A row exists with the same id but different content; refused to overwrite."""


class KnowledgeConnection:
    """One open SQLite connection to the knowledge database.

    Callers must use :meth:`close` exactly once; ``KnowledgeConnection`` is
    a context manager.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def raw(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "KnowledgeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# --------------------------------------------------------------------- I/O

_CORE_TABLES = (
    "documents",
    "document_products",
    "pages",
    "segments",
    "chunks",
    "chunk_links",
    "snapshots",
)


def _connect_writable(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _connect_readonly(database_path: Path) -> sqlite3.Connection:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    database_uri = database_path.resolve(strict=True).as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# ----------------------------------------------------------------- schema

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS documents (
        doc_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        corpus_id TEXT NOT NULL,
        source_url TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        document_revision TEXT NOT NULL,
        document_type TEXT NOT NULL,
        language TEXT NOT NULL,
        local_file TEXT NOT NULL,
        page_count INTEGER NOT NULL,
        document_reviewed INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        UNIQUE (source_id, sha256)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_products (
        doc_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        PRIMARY KEY (doc_id, product_id),
        FOREIGN KEY (doc_id) REFERENCES documents (doc_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pages (
        page_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        page_number INTEGER NOT NULL,
        raw_text TEXT NOT NULL,
        text_char_count INTEGER NOT NULL,
        image_count INTEGER NOT NULL,
        parse_status TEXT NOT NULL,
        section_hint TEXT,
        content_hash TEXT NOT NULL,
        UNIQUE (doc_id, page_number),
        FOREIGN KEY (doc_id) REFERENCES documents (doc_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS segments (
        segment_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        page_number INTEGER NOT NULL,
        sequence INTEGER NOT NULL,
        segment_type TEXT NOT NULL,
        raw_text TEXT NOT NULL,
        bbox_x0 REAL,
        bbox_y0 REAL,
        bbox_x1 REAL,
        bbox_y1 REAL,
        heading_path_json TEXT NOT NULL,
        quality_status TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES documents (doc_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        page_start INTEGER NOT NULL,
        page_end INTEGER NOT NULL,
        sequence INTEGER NOT NULL,
        raw_text TEXT NOT NULL,
        retrieval_text TEXT NOT NULL,
        estimated_tokens INTEGER NOT NULL,
        chunker_version TEXT NOT NULL,
        quality_status TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES documents (doc_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunk_links (
        source_chunk_id TEXT NOT NULL,
        target_chunk_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        doc_id TEXT NOT NULL,
        PRIMARY KEY (source_chunk_id, kind),
        FOREIGN KEY (source_chunk_id) REFERENCES chunks (chunk_id) ON DELETE CASCADE,
        FOREIGN KEY (target_chunk_id) REFERENCES chunks (chunk_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        snapshot_id TEXT PRIMARY KEY,
        corpus_id TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,
        knowledge_schema_version INTEGER NOT NULL,
        parser_version TEXT NOT NULL,
        chunker_version TEXT NOT NULL,
        status TEXT NOT NULL,
        document_count INTEGER NOT NULL,
        page_count INTEGER NOT NULL,
        segment_count INTEGER NOT NULL,
        chunk_count INTEGER NOT NULL,
        chunk_link_count INTEGER NOT NULL,
        needs_ocr_pages INTEGER NOT NULL,
        table_uncertain_pages INTEGER NOT NULL,
        warnings_json TEXT NOT NULL
    )
    """,
)


def initialize_knowledge_database(database_path: Path) -> KnowledgeConnection:
    """Create an empty knowledge database with schema v1 if missing."""

    connection = _connect_writable(database_path)
    try:
        with connection:
            connection.executescript(";".join(_SCHEMA_STATEMENTS))
            connection.execute(
                f"PRAGMA user_version = {KNOWLEDGE_SCHEMA_VERSION}"
            )
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        connection.close()
        raise KnowledgeSchemaError(str(exc)) from exc
    return KnowledgeConnection(connection)


def open_knowledge_database(database_path: Path) -> KnowledgeConnection:
    """Open an existing knowledge database for read-only inspection."""

    connection = _connect_readonly(database_path)
    return KnowledgeConnection(connection)


_CONTENT_COLUMNS_BY_TABLE: Mapping[str, tuple[str, ...]] = {
    "documents": (
        "source_id",
        "corpus_id",
        "source_url",
        "sha256",
        "document_revision",
        "document_type",
        "language",
        "local_file",
        "page_count",
        "document_reviewed",
        "payload_json",
    ),
    "pages": (
        "doc_id",
        "page_number",
        "raw_text",
        "text_char_count",
        "image_count",
        "parse_status",
        "section_hint",
        "content_hash",
    ),
    "segments": (
        "doc_id",
        "page_number",
        "sequence",
        "segment_type",
        "raw_text",
        "bbox_x0",
        "bbox_y0",
        "bbox_x1",
        "bbox_y1",
        "heading_path_json",
        "quality_status",
        "content_hash",
    ),
    "chunks": (
        "doc_id",
        "page_start",
        "page_end",
        "sequence",
        "raw_text",
        "retrieval_text",
        "estimated_tokens",
        "chunker_version",
        "quality_status",
        "content_hash",
    ),
    "chunk_links": (
        "source_chunk_id",
        "target_chunk_id",
        "kind",
        "doc_id",
    ),
}


def _existing_content_signature(
    connection: sqlite3.Connection,
    table: str,
    key_column: str,
    key_value: str,
) -> str | None:
    columns = _CONTENT_COLUMNS_BY_TABLE.get(table)
    if columns is None:
        raise KnowledgeError(f"unsupported table for content check: {table}")
    quoted_columns = ", ".join(columns)
    row = connection.execute(
        f"SELECT {quoted_columns} FROM {table} WHERE {key_column} = ?",
        (key_value,),
    ).fetchone()
    if row is None:
        return None
    return "|".join("" if value is None else repr(value) for value in row)


def _require_no_conflict(
    connection: sqlite3.Connection,
    table: str,
    key_column: str,
    key_value: str,
    expected_signature: str,
    *,
    label: str,
) -> None:
    existing = _existing_content_signature(
        connection, table, key_column, key_value
    )
    if existing is None:
        return
    if existing != expected_signature:
        raise KnowledgeConflict(
            f"{label} content conflict for {key_column}={key_value}"
        )


# ---------------------------------------------------------------- writes

def save_document(
    connection: KnowledgeConnection,
    document: DocumentRecord,
    product_ids: Iterable[str],
) -> None:
    """Insert or update one document and its product links."""

    payload = json.dumps(
        {
            "doc_id": document.doc_id,
            "source_id": document.source_id,
            "corpus_id": document.corpus_id,
            "source_url": document.source_url,
            "sha256": document.sha256,
            "document_revision": document.document_revision,
            "document_type": document.document_type,
            "language": document.language,
            "local_file": str(document.local_file),
            "page_count": document.page_count,
            "document_reviewed": document.document_reviewed,
        },
        sort_keys=True,
        ensure_ascii=False,
    )

    raw = connection.raw
    with raw:
            document_signature = "|".join(
                repr(value)
                for value in (
                    document.source_id,
                    document.corpus_id,
                    document.source_url,
                    document.sha256,
                    document.document_revision,
                    document.document_type,
                    document.language,
                    str(document.local_file),
                    document.page_count,
                    int(document.document_reviewed),
                    payload,
                )
            )
            _require_no_conflict(
                raw,
                "documents",
                "doc_id",
                document.doc_id,
                document_signature,
                label="document",
            )
            raw.execute(
                """
                INSERT INTO documents (
                    doc_id, source_id, corpus_id, source_url, sha256,
                    document_revision, document_type, language, local_file,
                    page_count, document_reviewed, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (doc_id) DO UPDATE SET
                    source_id = excluded.source_id,
                    corpus_id = excluded.corpus_id,
                    source_url = excluded.source_url,
                    sha256 = excluded.sha256,
                    document_revision = excluded.document_revision,
                    document_type = excluded.document_type,
                    language = excluded.language,
                    local_file = excluded.local_file,
                    page_count = excluded.page_count,
                    document_reviewed = excluded.document_reviewed,
                    payload_json = excluded.payload_json
                """,
                (
                    document.doc_id,
                    document.source_id,
                    document.corpus_id,
                    document.source_url,
                    document.sha256,
                    document.document_revision,
                    document.document_type,
                    document.language,
                    str(document.local_file),
                    document.page_count,
                    int(document.document_reviewed),
                    payload,
                ),
            )

            # Product links are recreated to mirror the manifest exactly.
            raw.execute(
                "DELETE FROM document_products WHERE doc_id = ?",
                (document.doc_id,),
            )
            for product_id in sorted(set(product_ids)):
                raw.execute(
                    """
                    INSERT INTO document_products (doc_id, product_id)
                    VALUES (?, ?)
                    ON CONFLICT (doc_id, product_id) DO NOTHING
                    """,
                    (document.doc_id, product_id),
                )


def save_pages(
    connection: KnowledgeConnection,
    pages: Iterable[PageRecord],
) -> None:
    raw = connection.raw
    signatures_by_id: dict[str, str] = {}
    rows: list[tuple[object, ...]] = []

    for page in pages:
        signature = "|".join(
            "" if value is None else repr(value)
            for value in (
                page.doc_id,
                page.page_number,
                page.raw_text,
                page.text_char_count,
                page.image_count,
                page.parse_status.value,
                page.section_hint,
                page.content_hash,
            )
        )
        signatures_by_id[page.page_id] = signature
        rows.append(
            (
                page.page_id,
                page.doc_id,
                page.page_number,
                page.raw_text,
                page.text_char_count,
                page.image_count,
                page.parse_status.value,
                page.section_hint,
                page.content_hash,
            )
        )

    if not rows:
        return

    with raw:
            for page_id, signature in signatures_by_id.items():
                _require_no_conflict(
                    raw,
                    "pages",
                    "page_id",
                    page_id,
                    signature,
                    label="page",
                )
            raw.executemany(
                """
                INSERT INTO pages (
                    page_id, doc_id, page_number, raw_text, text_char_count,
                    image_count, parse_status, section_hint, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (page_id) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    page_number = excluded.page_number,
                    raw_text = excluded.raw_text,
                    text_char_count = excluded.text_char_count,
                    image_count = excluded.image_count,
                    parse_status = excluded.parse_status,
                    section_hint = excluded.section_hint,
                    content_hash = excluded.content_hash
                """,
                rows,
            )


def save_segments(
    connection: KnowledgeConnection,
    segments: Iterable[SegmentRecord],
) -> None:
    rows: list[tuple[object, ...]] = []
    signatures_by_id: dict[str, str] = {}

    for segment in segments:
        bbox = segment.bbox
        bbox_columns = (
            bbox[0] if bbox else None,
            bbox[1] if bbox else None,
            bbox[2] if bbox else None,
            bbox[3] if bbox else None,
        )
        heading_path_json = json.dumps(
            list(segment.heading_path), sort_keys=True
        )
        signature = "|".join(
            "" if value is None else repr(value)
            for value in (
                segment.doc_id,
                segment.page_number,
                segment.sequence,
                segment.segment_type.value,
                segment.raw_text,
                bbox_columns[0],
                bbox_columns[1],
                bbox_columns[2],
                bbox_columns[3],
                heading_path_json,
                segment.quality_status.value,
                segment.content_hash,
            )
        )
        signatures_by_id[segment.segment_id] = signature
        rows.append(
            (
                segment.segment_id,
                segment.doc_id,
                segment.page_number,
                segment.sequence,
                segment.segment_type.value,
                segment.raw_text,
                bbox_columns[0],
                bbox_columns[1],
                bbox_columns[2],
                bbox_columns[3],
                heading_path_json,
                segment.quality_status.value,
                segment.content_hash,
            )
        )

    if not rows:
        return

    raw = connection.raw
    with raw:
            for segment_id, signature in signatures_by_id.items():
                _require_no_conflict(
                    raw,
                    "segments",
                    "segment_id",
                    segment_id,
                    signature,
                    label="segment",
                )
            raw.executemany(
                """
                INSERT INTO segments (
                    segment_id, doc_id, page_number, sequence, segment_type,
                    raw_text, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                    heading_path_json, quality_status, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (segment_id) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    page_number = excluded.page_number,
                    sequence = excluded.sequence,
                    segment_type = excluded.segment_type,
                    raw_text = excluded.raw_text,
                    bbox_x0 = excluded.bbox_x0,
                    bbox_y0 = excluded.bbox_y0,
                    bbox_x1 = excluded.bbox_x1,
                    bbox_y1 = excluded.bbox_y1,
                    heading_path_json = excluded.heading_path_json,
                    quality_status = excluded.quality_status,
                    content_hash = excluded.content_hash
                """,
                rows,
            )


def save_chunks(
    connection: KnowledgeConnection,
    chunks: Iterable[ChunkRecord],
) -> None:
    rows: list[tuple[object, ...]] = []
    signatures_by_id: dict[str, str] = {}

    for chunk in chunks:
        signature = "|".join(
            "" if value is None else repr(value)
            for value in (
                chunk.doc_id,
                chunk.page_start,
                chunk.page_end,
                chunk.sequence,
                chunk.raw_text,
                chunk.retrieval_text,
                chunk.estimated_tokens,
                chunk.chunker_version,
                chunk.quality_status.value,
                chunk.content_hash,
            )
        )
        signatures_by_id[chunk.chunk_id] = signature
        rows.append(
            (
                chunk.chunk_id,
                chunk.doc_id,
                chunk.page_start,
                chunk.page_end,
                chunk.sequence,
                chunk.raw_text,
                chunk.retrieval_text,
                chunk.estimated_tokens,
                chunk.chunker_version,
                chunk.quality_status.value,
                chunk.content_hash,
            )
        )

    if not rows:
        return

    raw = connection.raw
    with raw:
            for chunk_id, signature in signatures_by_id.items():
                _require_no_conflict(
                    raw,
                    "chunks",
                    "chunk_id",
                    chunk_id,
                    signature,
                    label="chunk",
                )
            raw.executemany(
                """
                INSERT INTO chunks (
                    chunk_id, doc_id, page_start, page_end, sequence,
                    raw_text, retrieval_text, estimated_tokens,
                    chunker_version, quality_status, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    page_start = excluded.page_start,
                    page_end = excluded.page_end,
                    sequence = excluded.sequence,
                    raw_text = excluded.raw_text,
                    retrieval_text = excluded.retrieval_text,
                    estimated_tokens = excluded.estimated_tokens,
                    chunker_version = excluded.chunker_version,
                    quality_status = excluded.quality_status,
                    content_hash = excluded.content_hash
                """,
                rows,
            )


def save_chunk_links(
    connection: KnowledgeConnection,
    links: Iterable[ChunkLinkRecord],
) -> None:
    rows = [
        (
            link.source_chunk_id,
            link.target_chunk_id,
            link.kind.value,
            link.doc_id,
        )
        for link in links
    ]

    if not rows:
        return

    raw = connection.raw
    with raw:
            raw.executemany(
                """
                INSERT INTO chunk_links (
                    source_chunk_id, target_chunk_id, kind, doc_id
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (source_chunk_id, kind) DO UPDATE SET
                    target_chunk_id = excluded.target_chunk_id,
                    doc_id = excluded.doc_id
                """,
                rows,
            )


def save_snapshot(
    connection: KnowledgeConnection,
    snapshot: SnapshotRecord,
) -> None:
    raw = connection.raw
    with raw:
            raw.execute(
                """
                INSERT INTO snapshots (
                    snapshot_id, corpus_id, manifest_sha256,
                    knowledge_schema_version, parser_version, chunker_version,
                    status, document_count, page_count, segment_count,
                    chunk_count, chunk_link_count, needs_ocr_pages,
                    table_uncertain_pages, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_id) DO UPDATE SET
                    corpus_id = excluded.corpus_id,
                    manifest_sha256 = excluded.manifest_sha256,
                    knowledge_schema_version = excluded.knowledge_schema_version,
                    parser_version = excluded.parser_version,
                    chunker_version = excluded.chunker_version,
                    status = excluded.status,
                    document_count = excluded.document_count,
                    page_count = excluded.page_count,
                    segment_count = excluded.segment_count,
                    chunk_count = excluded.chunk_count,
                    chunk_link_count = excluded.chunk_link_count,
                    needs_ocr_pages = excluded.needs_ocr_pages,
                    table_uncertain_pages = excluded.table_uncertain_pages,
                    warnings_json = excluded.warnings_json
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.corpus_id,
                    snapshot.manifest_sha256,
                    snapshot.knowledge_schema_version,
                    snapshot.parser_version,
                    snapshot.chunker_version,
                    snapshot.status,
                    snapshot.document_count,
                    snapshot.page_count,
                    snapshot.segment_count,
                    snapshot.chunk_count,
                    snapshot.chunk_link_count,
                    snapshot.needs_ocr_pages,
                    snapshot.table_uncertain_pages,
                    json.dumps(list(snapshot.warnings), ensure_ascii=False),
                ),
            )


# ----------------------------------------------------------------- reads

def _validate_schema(connection: sqlite3.Connection) -> None:
    version_row = connection.execute("PRAGMA user_version").fetchone()
    version = int(version_row[0]) if version_row else 0
    if version != KNOWLEDGE_SCHEMA_VERSION:
        raise KnowledgeSchemaError(
            f"unsupported knowledge schema version: {version}"
        )

    names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table'"
        ).fetchall()
    }
    missing = set(_CORE_TABLES) - names
    if missing:
        raise KnowledgeSchemaError(
            f"missing knowledge tables: {sorted(missing)}"
        )

    fk_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if fk_violations:
        raise KnowledgeSchemaError("knowledge foreign key violations detected")


def load_document(
    connection: KnowledgeConnection,
    doc_id: str,
) -> DocumentRecord | None:
    raw = connection.raw
    _validate_schema(raw)
    row = raw.execute(
        """
        SELECT doc_id, source_id, corpus_id, source_url, sha256,
               document_revision, document_type, language, local_file,
               page_count, document_reviewed
        FROM documents WHERE doc_id = ?
        """,
        (doc_id,),
    ).fetchone()
    if row is None:
        return None
    return DocumentRecord(
        doc_id=row[0],
        source_id=row[1],
        corpus_id=row[2],
        source_url=row[3],
        sha256=row[4],
        document_revision=row[5],
        document_type=row[6],
        language=row[7],
        local_file=Path(row[8]),
        page_count=row[9],
        document_reviewed=bool(row[10]),
    )


def load_page(
    connection: KnowledgeConnection,
    doc_id: str,
    page_number: int,
) -> PageRecord | None:
    raw = connection.raw
    _validate_schema(raw)
    row = raw.execute(
        """
        SELECT page_id, doc_id, page_number, raw_text, text_char_count,
               image_count, parse_status, section_hint, content_hash
        FROM pages WHERE doc_id = ? AND page_number = ?
        """,
        (doc_id, page_number),
    ).fetchone()
    if row is None:
        return None

    from .models import PageParseStatus

    return PageRecord(
        page_id=row[0],
        doc_id=row[1],
        page_number=row[2],
        raw_text=row[3],
        text_char_count=row[4],
        image_count=row[5],
        parse_status=PageParseStatus(row[6]),
        section_hint=row[7],
        content_hash=row[8],
    )


def load_chunk(
    connection: KnowledgeConnection,
    chunk_id: str,
) -> ChunkRecord | None:
    raw = connection.raw
    _validate_schema(raw)
    row = raw.execute(
        """
        SELECT chunk_id, doc_id, page_start, page_end, sequence, raw_text,
               retrieval_text, estimated_tokens, chunker_version,
               quality_status, content_hash
        FROM chunks WHERE chunk_id = ?
        """,
        (chunk_id,),
    ).fetchone()
    if row is None:
        return None

    from .models import ChunkQuality

    return ChunkRecord(
        chunk_id=row[0],
        doc_id=row[1],
        page_start=row[2],
        page_end=row[3],
        sequence=row[4],
        raw_text=row[5],
        retrieval_text=row[6],
        estimated_tokens=row[7],
        chunker_version=row[8],
        quality_status=ChunkQuality(row[9]),
        content_hash=row[10],
    )


def list_documents(
    connection: KnowledgeConnection,
) -> tuple[DocumentRecord, ...]:
    raw = connection.raw
    _validate_schema(raw)
    rows = raw.execute(
        """
        SELECT doc_id, source_id, corpus_id, source_url, sha256,
               document_revision, document_type, language, local_file,
               page_count, document_reviewed
        FROM documents ORDER BY doc_id
        """
    ).fetchall()
    return tuple(
        DocumentRecord(
            doc_id=row[0],
            source_id=row[1],
            corpus_id=row[2],
            source_url=row[3],
            sha256=row[4],
            document_revision=row[5],
            document_type=row[6],
            language=row[7],
            local_file=Path(row[8]),
            page_count=row[9],
            document_reviewed=bool(row[10]),
        )
        for row in rows
    )


def list_pages_for_document(
    connection: KnowledgeConnection,
    doc_id: str,
) -> tuple[PageRecord, ...]:
    from .models import PageParseStatus

    raw = connection.raw
    _validate_schema(raw)
    rows = raw.execute(
        """
        SELECT page_id, doc_id, page_number, raw_text, text_char_count,
               image_count, parse_status, section_hint, content_hash
        FROM pages WHERE doc_id = ? ORDER BY page_number
        """,
        (doc_id,),
    ).fetchall()
    return tuple(
        PageRecord(
            page_id=row[0],
            doc_id=row[1],
            page_number=row[2],
            raw_text=row[3],
            text_char_count=row[4],
            image_count=row[5],
            parse_status=PageParseStatus(row[6]),
            section_hint=row[7],
            content_hash=row[8],
        )
        for row in rows
    )


def list_chunks_for_document(
    connection: KnowledgeConnection,
    doc_id: str,
) -> tuple[ChunkRecord, ...]:
    from .models import ChunkQuality

    raw = connection.raw
    _validate_schema(raw)
    rows = raw.execute(
        """
        SELECT chunk_id, doc_id, page_start, page_end, sequence, raw_text,
               retrieval_text, estimated_tokens, chunker_version,
               quality_status, content_hash
        FROM chunks WHERE doc_id = ?
        ORDER BY page_start, page_end, sequence
        """,
        (doc_id,),
    ).fetchall()
    return tuple(
        ChunkRecord(
            chunk_id=row[0],
            doc_id=row[1],
            page_start=row[2],
            page_end=row[3],
            sequence=row[4],
            raw_text=row[5],
            retrieval_text=row[6],
            estimated_tokens=row[7],
            chunker_version=row[8],
            quality_status=ChunkQuality(row[9]),
            content_hash=row[10],
        )
        for row in rows
    )


def list_chunk_links_for_document(
    connection: KnowledgeConnection,
    doc_id: str,
) -> tuple[ChunkLinkRecord, ...]:
    raw = connection.raw
    _validate_schema(raw)
    rows = raw.execute(
        """
        SELECT source_chunk_id, target_chunk_id, kind, doc_id
        FROM chunk_links WHERE doc_id = ?
        ORDER BY source_chunk_id, kind
        """,
        (doc_id,),
    ).fetchall()
    return tuple(
        ChunkLinkRecord(
            source_chunk_id=row[0],
            target_chunk_id=row[1],
            kind=ChunkLinkKind(row[2]),
            doc_id=row[3],
        )
        for row in rows
    )


def list_snapshots(
    connection: KnowledgeConnection,
) -> tuple[SnapshotRecord, ...]:
    raw = connection.raw
    _validate_schema(raw)
    rows = raw.execute(
        """
        SELECT snapshot_id, corpus_id, manifest_sha256,
               knowledge_schema_version, parser_version, chunker_version,
               status, document_count, page_count, segment_count,
               chunk_count, chunk_link_count, needs_ocr_pages,
               table_uncertain_pages, warnings_json
        FROM snapshots ORDER BY snapshot_id
        """
    ).fetchall()
    snapshots: list[SnapshotRecord] = []
    for row in rows:
        warnings = tuple(json.loads(row[14]))
        snapshots.append(
            SnapshotRecord(
                snapshot_id=row[0],
                corpus_id=row[1],
                manifest_sha256=row[2],
                knowledge_schema_version=row[3],
                parser_version=row[4],
                chunker_version=row[5],
                status=row[6],
                document_count=row[7],
                page_count=row[8],
                segment_count=row[9],
                chunk_count=row[10],
                chunk_link_count=row[11],
                needs_ocr_pages=row[12],
                table_uncertain_pages=row[13],
                warnings=warnings,
            )
        )
    return tuple(snapshots)


def list_document_product_links(
    connection: KnowledgeConnection,
    *,
    doc_id: str | None = None,
) -> tuple[DocumentProductLink, ...]:
    raw = connection.raw
    _validate_schema(raw)
    if doc_id is None:
        rows = raw.execute(
            "SELECT doc_id, product_id FROM document_products "
            "ORDER BY doc_id, product_id"
        ).fetchall()
    else:
        rows = raw.execute(
            "SELECT doc_id, product_id FROM document_products "
            "WHERE doc_id = ? ORDER BY doc_id, product_id",
            (doc_id,),
        ).fetchall()
    return tuple(DocumentProductLink(doc_id=row[0], product_id=row[1]) for row in rows)


def compute_manifest_sha256(manifest_path: Path) -> str:
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest().upper()


def verify_known_tables(connection: KnowledgeConnection) -> Mapping[str, int]:
    """Return a mapping of table name to row count for diagnostic use."""

    raw = connection.raw
    counts: dict[str, int] = {}
    for table in _CORE_TABLES:
        try:
            row = raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0])
        except sqlite3.Error:  # pragma: no cover - defensive
            counts[table] = -1
    return counts