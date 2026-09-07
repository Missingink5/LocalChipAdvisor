"""Contract tests for the knowledge SQLite repository."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from local_chip_advisor.knowledge.models import (
    ChunkLinkKind,
    ChunkLinkRecord,
    ChunkQuality,
    ChunkRecord,
    DocumentRecord,
    KNOWLEDGE_SCHEMA_VERSION,
    PageParseStatus,
    PageRecord,
    SegmentRecord,
    SegmentType,
    SnapshotRecord,
)
from local_chip_advisor.knowledge.repository import (
    KnowledgeConflict,
    KnowledgeConnection,
    KnowledgeSchemaError,
    initialize_knowledge_database,
    list_chunk_links_for_document,
    list_chunks_for_document,
    list_document_product_links,
    list_documents,
    list_pages_for_document,
    list_snapshots,
    load_chunk,
    load_document,
    load_page,
    open_knowledge_database,
    save_chunk_links,
    save_chunks,
    save_document,
    save_pages,
    save_segments,
    save_snapshot,
    verify_known_tables,
)


def _sample_document(doc_id: str = "doc:mps:aabbccddeeff") -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        source_id="mps-mp4570-datasheet",
        corpus_id="s04-corpus-v1",
        source_url="https://example/mp4570.pdf",
        sha256="A" * 64,
        document_revision="1.01",
        document_type="datasheet",
        language="en",
        local_file=Path("data/raw/mps/MP4570/MP4570_Datasheet.pdf"),
        page_count=22,
        document_reviewed=True,
    )


def _sample_page(doc_id: str, page_number: int, *, text: str = "raw text") -> PageRecord:
    return PageRecord(
        page_id=f"{doc_id}:p{page_number:04d}",
        doc_id=doc_id,
        page_number=page_number,
        raw_text=text,
        text_char_count=len(text),
        image_count=0,
        parse_status=PageParseStatus.OK,
        section_hint=None,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _sample_chunk(doc_id: str, sequence: int, *, text: str = "raw") -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"chunk:{doc_id}:seq{sequence:04d}:v1:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}",
        doc_id=doc_id,
        page_start=1,
        page_end=1,
        sequence=sequence,
        raw_text=text,
        retrieval_text=text,
        estimated_tokens=1,
        chunker_version="structure-chunker-v1",
        quality_status=ChunkQuality.OK,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def test_initialize_creates_schema_with_user_version(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"

    connection = initialize_knowledge_database(database)

    try:
        version = connection.raw.execute("PRAGMA user_version").fetchone()[0]
        assert version == KNOWLEDGE_SCHEMA_VERSION
        names = {
            row[0]
            for row in connection.raw.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            ).fetchall()
        }
        for table in (
            "documents",
            "document_products",
            "pages",
            "segments",
            "chunks",
            "chunk_links",
            "snapshots",
        ):
            assert table in names
    finally:
        connection.close()


def test_initialize_creates_parent_directory(tmp_path: Path) -> None:
    database = tmp_path / "nested" / "knowledge.sqlite3"

    connection = initialize_knowledge_database(database)

    try:
        assert database.is_file()
    finally:
        connection.close()


def test_open_readonly_rejects_missing_database(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_knowledge_database(tmp_path / "absent.sqlite3")


def test_open_readonly_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)
    connection.close()

    raw = sqlite3.connect(database)
    raw.execute("PRAGMA user_version = 99")
    raw.commit()
    raw.close()

    readonly = open_knowledge_database(database)
    try:
        with pytest.raises(KnowledgeSchemaError, match="schema version"):
            list_documents(readonly)
    finally:
        readonly.close()


def test_open_readonly_rejects_missing_core_table(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)
    connection.close()

    raw = sqlite3.connect(database)
    raw.execute("DROP TABLE chunk_links")
    raw.commit()
    raw.close()

    readonly = open_knowledge_database(database)
    try:
        with pytest.raises(KnowledgeSchemaError, match="missing knowledge tables"):
            list_chunks_for_document(readonly, "doc:mps:aabbccddeeff")
    finally:
        readonly.close()


def test_save_and_load_document_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        document = _sample_document()
        save_document(connection, document, ["MP4570"])
        loaded = load_document(connection, document.doc_id)
        assert loaded == document

        links = list_document_product_links(connection, doc_id=document.doc_id)
        assert [link.product_id for link in links] == ["MP4570"]
    finally:
        connection.close()


def test_save_document_is_idempotent_on_identical_payload(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        document = _sample_document()
        save_document(connection, document, ["MP4570"])
        save_document(connection, document, ["MP4570"])

        documents = list_documents(connection)
        assert len(documents) == 1
    finally:
        connection.close()


def test_save_document_raises_conflict_when_payload_changes(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        save_document(connection, _sample_document(), ["MP4570"])
        altered = _sample_document()
        # Object is frozen; rebuild with a different revision to force conflict.
        altered = DocumentRecord(
            doc_id=altered.doc_id,
            source_id=altered.source_id,
            corpus_id=altered.corpus_id,
            source_url=altered.source_url,
            sha256=altered.sha256,
            document_revision="1.02",
            document_type=altered.document_type,
            language=altered.language,
            local_file=altered.local_file,
            page_count=altered.page_count,
            document_reviewed=altered.document_reviewed,
        )

        with pytest.raises(KnowledgeConflict):
            save_document(connection, altered, ["MP4570"])
    finally:
        connection.close()


def test_save_pages_round_trip_with_status(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        document = _sample_document()
        save_document(connection, document, ["MP4570"])

        page_one = _sample_page(document.doc_id, 1, text="page one")
        page_two = PageRecord(
            page_id=f"{document.doc_id}:p{2:04d}",
            doc_id=page_one.doc_id,
            page_number=2,
            raw_text="page two",
            text_char_count=len("page two"),
            image_count=0,
            parse_status=PageParseStatus.TABLE_UNCERTAIN,
            section_hint=None,
            content_hash=hashlib.sha256(b"page two").hexdigest(),
        )
        save_pages(connection, (page_one, page_two))

        loaded = list_pages_for_document(connection, document.doc_id)
        assert [page.page_number for page in loaded] == [1, 2]
        assert loaded[1].parse_status is PageParseStatus.TABLE_UNCERTAIN
        assert load_page(connection, document.doc_id, 1).raw_text == "page one"
    finally:
        connection.close()


def test_save_chunks_and_links_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        document = _sample_document()
        save_document(connection, document, ["MP4570"])
        save_pages(
            connection,
            (_sample_page(document.doc_id, 1),),
        )

        first = _sample_chunk(document.doc_id, 0, text="first chunk")
        second = _sample_chunk(document.doc_id, 1, text="second chunk")
        save_chunks(connection, (first, second))
        save_chunk_links(
            connection,
            (
                ChunkLinkRecord(
                    source_chunk_id=first.chunk_id,
                    target_chunk_id=second.chunk_id,
                    kind=ChunkLinkKind.NEXT,
                    doc_id=document.doc_id,
                ),
            ),
        )

        chunks = list_chunks_for_document(connection, document.doc_id)
        assert [chunk.sequence for chunk in chunks] == [0, 1]
        assert load_chunk(connection, first.chunk_id) == first

        links = list_chunk_links_for_document(connection, document.doc_id)
        assert len(links) == 1
        assert links[0].kind is ChunkLinkKind.NEXT
    finally:
        connection.close()


def test_save_chunks_rejects_conflicting_payload(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        document = _sample_document()
        save_document(connection, document, ["MP4570"])
        save_pages(connection, (_sample_page(document.doc_id, 1),))

        first = _sample_chunk(document.doc_id, 0, text="first chunk")
        save_chunks(connection, (first,))

        altered = ChunkRecord(
            chunk_id=first.chunk_id,
            doc_id=first.doc_id,
            page_start=first.page_start,
            page_end=first.page_end,
            sequence=first.sequence,
            raw_text="mutated raw",
            retrieval_text="mutated retrieval",
            estimated_tokens=first.estimated_tokens,
            chunker_version=first.chunker_version,
            quality_status=first.quality_status,
            content_hash=hashlib.sha256(b"mutated").hexdigest(),
        )

        with pytest.raises(KnowledgeConflict):
            save_chunks(connection, (altered,))
    finally:
        connection.close()


def test_save_snapshot_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        snapshot = SnapshotRecord(
            snapshot_id="build:s04-corpus-v1:abc",
            corpus_id="s04-corpus-v1",
            manifest_sha256="A" * 64,
            knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION,
            parser_version="pdf-parser-v2",
            chunker_version="structure-chunker-v1",
            status="BUILDING",
            document_count=4,
            page_count=113,
            segment_count=200,
            chunk_count=150,
            chunk_link_count=300,
            needs_ocr_pages=0,
            table_uncertain_pages=4,
            warnings=("no warnings",),
        )
        save_snapshot(connection, snapshot)
        snapshots = list_snapshots(connection)
        assert len(snapshots) == 1
        assert snapshots[0].warnings == ("no warnings",)
    finally:
        connection.close()


def test_verify_known_tables_returns_counts(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        counts = verify_known_tables(connection)
        assert counts["documents"] == 0
        assert counts["pages"] == 0
        assert counts["chunks"] == 0
    finally:
        connection.close()


def test_segments_round_trip_with_bbox(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    try:
        document = _sample_document()
        save_document(connection, document, ["MP4570"])
        save_pages(connection, (_sample_page(document.doc_id, 1),))

        segment = SegmentRecord(
            segment_id=f"{document.doc_id}:p0001:s0000:pdf-parser-v2",
            doc_id=document.doc_id,
            page_number=1,
            sequence=0,
            segment_type=SegmentType.PARAGRAPH,
            raw_text="body paragraph",
            bbox=(10.0, 20.0, 100.0, 200.0),
            heading_path=("Section A", "Sub B"),
            quality_status=ChunkQuality.OK,
            content_hash=hashlib.sha256(b"body paragraph").hexdigest(),
        )
        save_segments(connection, (segment,))

        rows = connection.raw.execute(
            "SELECT segment_type, bbox_x0, bbox_y0, bbox_x1, bbox_y1, "
            "heading_path_json FROM segments WHERE segment_id = ?",
            (segment.segment_id,),
        ).fetchone()
        assert rows is not None
        assert rows[0] == "PARAGRAPH"
        assert rows[1:] == (10.0, 20.0, 100.0, 200.0, '["Section A", "Sub B"]')
    finally:
        connection.close()


def test_knowledge_connection_is_context_manager(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    with connection as ctx:
        assert isinstance(ctx, KnowledgeConnection)
        assert ctx.raw.execute("PRAGMA user_version").fetchone()[0] == 1


def test_readonly_connection_enforces_query_only(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    writable = initialize_knowledge_database(database)
    writable.close()

    readonly = open_knowledge_database(database)
    try:
        with pytest.raises(sqlite3.OperationalError):
            readonly.raw.execute(
                "INSERT INTO documents (doc_id, source_id, corpus_id, source_url, "
                "sha256, document_revision, document_type, language, local_file, "
                "page_count, document_reviewed, payload_json) "
                "VALUES ('x', 'x', 'x', 'x', 'x', 'x', 'x', 'x', 'x', 1, 0, '{}')"
            )
    finally:
        readonly.close()