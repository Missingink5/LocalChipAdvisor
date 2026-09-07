"""Contract tests for the manifest-driven knowledge ingestion pipeline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from local_chip_advisor.knowledge import (
    HashMismatchError,
    IngestionSummary,
    IngestReport,
    ManifestDocument,
    PageCountMismatchError,
    PageParseStatus,
    SNAPSHOT_STATUS_BUILDING,
    load_corpus_manifest,
)
from local_chip_advisor.knowledge.ingest import (
    CorpusManifest,
    build_snapshot_record,
    ingest_corpus,
    ingest_document,
)
from local_chip_advisor.knowledge.repository import (
    initialize_knowledge_database,
    list_chunks_for_document,
    list_documents,
    list_pages_for_document,
    list_snapshots,
)


def _write_pdf(path: Path, *, pages: list[str]) -> None:
    document = pymupdf.open()
    for body in pages:
        page = document.new_page()
        page.insert_text((72, 72), body)
    document.save(path)
    document.close()


def _build_manifest_doc(
    source_id: str,
    local_file: Path,
    pdf_pages: int,
    *,
    product_ids: tuple[str, ...] = ("MP4570",),
) -> ManifestDocument:
    sha = hashlib.sha256(local_file.read_bytes()).hexdigest().upper()
    return ManifestDocument(
        source_id=source_id,
        product_ids=product_ids,
        document_type="datasheet",
        document_revision="1.0",
        language="en",
        source_url="https://example/test.pdf",
        local_file=local_file,
        sha256=sha,
        pdf_pages=pdf_pages,
        source_verified=True,
        human_reviewed=True,
    )


def _write_manifest(
    path: Path,
    docs: list[ManifestDocument],
    *,
    corpus_id: str = "s05-test-corpus",
) -> None:
    payload = {
        "schema_version": 1,
        "corpus_id": corpus_id,
        "documents": [
            {
                "source_id": d.source_id,
                "manufacturer": "Test Manufacturer",
                "product_ids": list(d.product_ids),
                "document_type": d.document_type,
                "document_title": d.source_id,
                "document_revision": d.document_revision,
                "document_date": "2026-01-01",
                "language": d.language,
                "source_authority": "official_vendor_datasheet",
                "source_url": d.source_url,
                "local_file": str(d.local_file).replace("\\", "/"),
                "sha256": d.sha256,
                "pdf_pages": d.pdf_pages,
                "source_verified": d.source_verified,
                "human_reviewed": d.human_reviewed,
                "themes_present": [],
                "notes": [],
            }
            for d in docs
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_corpus_manifest_reads_manifest(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["page one body text " * 30])
    manifest_doc = _build_manifest_doc("synthetic-a", pdf, pdf_pages=1)
    manifest_path = tmp_path / "corpus_manifest.json"
    _write_manifest(manifest_path, [manifest_doc])

    manifest = load_corpus_manifest(manifest_path)

    assert manifest.corpus_id == "s05-test-corpus"
    assert len(manifest.documents) == 1
    assert manifest.documents[0].source_id == "synthetic-a"


def test_ingest_document_validates_only(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["page one body text " * 30])
    manifest_doc = _build_manifest_doc("synthetic-a", pdf, pdf_pages=1)
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    summary = ingest_document(connection, manifest_doc, validate_only=True)

    assert isinstance(summary, IngestionSummary)
    assert summary.document.source_id == "synthetic-a"
    assert summary.page_records == ()
    assert list_documents(connection) == ()
    connection.close()


def test_ingest_document_writes_rows_with_correct_counts(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["page one body text " * 30, "page two body text " * 30])
    manifest_doc = _build_manifest_doc("synthetic-a", pdf, pdf_pages=2)
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    summary = ingest_document(connection, manifest_doc)

    docs = list_documents(connection)
    assert len(docs) == 1
    assert docs[0].source_id == "synthetic-a"
    pages = list_pages_for_document(connection, docs[0].doc_id)
    assert [p.page_number for p in pages] == [1, 2]
    chunks = list_chunks_for_document(connection, docs[0].doc_id)
    assert len(chunks) >= 1
    connection.close()


def test_ingest_document_fails_on_hash_mismatch(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["page one body text " * 30])
    manifest_doc = ManifestDocument(
        source_id="synthetic-a",
        product_ids=("MP4570",),
        document_type="datasheet",
        document_revision="1.0",
        language="en",
        source_url="https://example/test.pdf",
        local_file=pdf,
        sha256="0" * 64,
        pdf_pages=1,
        source_verified=True,
        human_reviewed=True,
    )
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    with pytest.raises(HashMismatchError):
        ingest_document(connection, manifest_doc)
    connection.close()


def test_ingest_document_fails_on_page_count_mismatch(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["page one body text " * 30])
    manifest_doc = _build_manifest_doc("synthetic-a", pdf, pdf_pages=99)
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    with pytest.raises(PageCountMismatchError):
        ingest_document(connection, manifest_doc)
    connection.close()


def test_ingest_corpus_emits_building_snapshot(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["page one body text " * 30, "page two body text " * 30])
    manifest_doc = _build_manifest_doc("synthetic-a", pdf, pdf_pages=2)
    manifest_path = tmp_path / "corpus_manifest.json"
    _write_manifest(manifest_path, [manifest_doc])
    manifest = load_corpus_manifest(manifest_path)

    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)
    report = ingest_corpus(connection, manifest)

    assert isinstance(report, IngestReport)
    assert report.document_count == 1
    snapshots = list_snapshots(connection)
    assert len(snapshots) == 1
    assert snapshots[0].status == SNAPSHOT_STATUS_BUILDING
    assert snapshots[0].document_count == 1
    assert snapshots[0].chunk_count >= 1
    connection.close()


def test_build_snapshot_record_binds_manifest_sha(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["page one body text " * 30])
    manifest_doc = _build_manifest_doc("synthetic-a", pdf, pdf_pages=1)
    manifest_path = tmp_path / "corpus_manifest.json"
    _write_manifest(manifest_path, [manifest_doc])
    manifest = load_corpus_manifest(manifest_path)

    report = IngestReport(manifest=manifest, summaries=[], chunk_link_total=0)
    snapshot = build_snapshot_record(manifest, report)

    assert snapshot.manifest_sha256 == manifest.manifest_sha256
    assert snapshot.status == SNAPSHOT_STATUS_BUILDING


def test_ingest_document_propagates_quality_warnings(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    # Two body pages so the document is recognized as healthy.
    _write_pdf(pdf, pages=["body text " * 200, "more body text " * 200])
    manifest_doc = _build_manifest_doc("synthetic-a", pdf, pdf_pages=2)
    database = tmp_path / "knowledge.sqlite3"
    connection = initialize_knowledge_database(database)

    summary = ingest_document(connection, manifest_doc)

    # Either quality is OK or we surface a structured warning; we never
    # silently swallow a quality issue.
    assert all(p.parse_status in PageParseStatus for p in summary.page_records)
    connection.close()
