"""Manifest-driven knowledge ingestion pipeline.

S05 stops at parse / segment / chunk / store. It does not perform any
embedding, BM25, hybrid retrieval, or LLM answer generation. The
ingest pipeline here is responsible only for:

1. reading ``corpus_manifest.json`` (the S04 durable pointer);
2. validating ``source_verified`` / ``human_reviewed`` / SHA / page count;
3. parsing the local PDF with the S05 layout parser;
4. classifying pages, segmenting, chunking, linking;
5. writing the per-document records into the knowledge SQLite store;
6. emitting an :class:`IngestionSummary` per document plus a top-level
   build :class:`SnapshotRecord` whose status remains ``BUILDING`` until
   S07 flips it to ``READY``.

No HTTP, no LLM, no embedding — only local deterministic code.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..ingestion import parse_pdf_layout
from .chunking import chunk_document
from .linking import link_chunks
from .models import (
    CHUNKER_VERSION,
    KNOWLEDGE_SCHEMA_VERSION,
    PARSER_VERSION,
    SNAPSHOT_STATUS_BUILDING,
    DocumentRecord,
    IngestionSummary,
    PageParseStatus,
    PageRecord,
    SnapshotRecord,
    derive_doc_id,
    derive_snapshot_id,
)
from .quality import classify_page
from .repository import (
    KnowledgeConflict,
    KnowledgeConnection,
    save_chunks,
    save_chunk_links,
    save_document,
    save_pages,
    save_segments,
    save_snapshot,
)
from .segmentation import segment_page


# ---------------------------------------------------------------------------
# Manifest model (very small, no Pydantic dep here)
# ---------------------------------------------------------------------------


class IngestError(RuntimeError):
    """Raised when corpus / source validation fails before any write."""


class HashMismatchError(IngestError):
    """Local PDF hash does not match the manifest's sha256."""


class PageCountMismatchError(IngestError):
    """Local PDF page count does not match the manifest's pdf_pages."""


@dataclass(frozen=True)
class ManifestDocument:
    source_id: str
    product_ids: tuple[str, ...]
    document_type: str
    document_revision: str
    language: str
    source_url: str
    local_file: Path
    sha256: str
    pdf_pages: int
    source_verified: bool
    human_reviewed: bool


@dataclass(frozen=True)
class CorpusManifest:
    schema_version: int
    corpus_id: str
    documents: tuple[ManifestDocument, ...]
    manifest_path: Path
    manifest_sha256: str


def load_corpus_manifest(path: Path) -> CorpusManifest:
    """Load and minimally validate ``corpus_manifest.json``."""

    if not path.is_file():
        raise IngestError(f"corpus manifest not found: {path}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest().upper()

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise IngestError(f"corpus manifest is not valid JSON: {path}") from exc

    schema_version = int(payload.get("schema_version", 0))
    corpus_id = str(payload.get("corpus_id", ""))
    raw_documents = payload.get("documents", [])
    if not corpus_id:
        raise IngestError("corpus manifest missing corpus_id")
    if not isinstance(raw_documents, list):
        raise IngestError("corpus manifest documents must be a list")

    documents: list[ManifestDocument] = []
    for entry in raw_documents:
        documents.append(_coerce_manifest_document(entry))

    return CorpusManifest(
        schema_version=schema_version,
        corpus_id=corpus_id,
        documents=tuple(documents),
        manifest_path=path,
        manifest_sha256=digest,
    )


def _coerce_manifest_document(entry: dict[str, Any]) -> ManifestDocument:
    required = (
        "source_id",
        "product_ids",
        "document_type",
        "document_revision",
        "language",
        "source_url",
        "local_file",
        "sha256",
        "pdf_pages",
        "source_verified",
        "human_reviewed",
    )
    missing = [name for name in required if name not in entry]
    if missing:
        raise IngestError(f"manifest entry missing required fields: {missing}")
    local_file = Path(entry["local_file"])
    return ManifestDocument(
        source_id=str(entry["source_id"]),
        product_ids=tuple(str(p) for p in entry["product_ids"]),
        document_type=str(entry["document_type"]),
        document_revision=str(entry["document_revision"]),
        language=str(entry["language"]),
        source_url=str(entry["source_url"]),
        local_file=local_file,
        sha256=str(entry["sha256"]).upper(),
        pdf_pages=int(entry["pdf_pages"]),
        source_verified=bool(entry["source_verified"]),
        human_reviewed=bool(entry["human_reviewed"]),
    )


# ---------------------------------------------------------------------------
# Per-document ingestion
# ---------------------------------------------------------------------------


@dataclass
class IngestReport:
    """Top-level result of one ingestion run over the corpus manifest."""

    manifest: CorpusManifest
    summaries: list[IngestionSummary] = field(default_factory=list)
    chunk_link_total: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def document_count(self) -> int:
        return len(self.summaries)

    @property
    def page_count(self) -> int:
        return sum(len(s.page_records) for s in self.summaries)

    @property
    def segment_count(self) -> int:
        return sum(len(s.segment_records) for s in self.summaries)

    @property
    def chunk_count(self) -> int:
        return sum(len(s.chunk_records) for s in self.summaries)

    @property
    def needs_ocr_pages(self) -> int:
        return sum(
            1 for s in self.summaries for p in s.page_records if p.needs_ocr
        )

    @property
    def table_uncertain_pages(self) -> int:
        return sum(
            1
            for s in self.summaries
            for p in s.page_records
            if p.parse_status is PageParseStatus.TABLE_UNCERTAIN
        )


def ingest_document(
    connection: KnowledgeConnection,
    manifest: ManifestDocument,
    *,
    validate_only: bool = False,
) -> IngestionSummary:
    """Ingest one manifest entry into the open knowledge connection.

    ``validate_only=True`` performs manifest validation, hash check, and
    page count check without writing anything to the database.
    """

    if not manifest.source_verified:
        raise IngestError(
            f"{manifest.source_id}: source_verified is false in manifest"
        )

    if not manifest.local_file.is_file():
        raise IngestError(
            f"{manifest.source_id}: local PDF not found at {manifest.local_file}"
        )

    parsed = parse_pdf_layout(manifest.local_file)
    actual_sha = parsed.sha256.upper()
    if actual_sha != manifest.sha256:
        raise HashMismatchError(
            f"{manifest.source_id}: sha256 mismatch (manifest={manifest.sha256}, "
            f"actual={actual_sha})"
        )
    if parsed.page_count != manifest.pdf_pages:
        raise PageCountMismatchError(
            f"{manifest.source_id}: pdf_pages mismatch (manifest={manifest.pdf_pages}, "
            f"actual={parsed.page_count})"
        )

    if validate_only:
        return IngestionSummary(
            document=_build_document_record(manifest, actual_sha, parsed.page_count),
            page_records=(),
            segment_records=(),
            chunk_records=(),
            warnings=(),
        )

    doc_record = _build_document_record(manifest, actual_sha, parsed.page_count)
    save_document(connection, doc_record, manifest.product_ids)

    page_records, segments = _build_page_records_and_segments(
        doc_record.doc_id, parsed.pages
    )
    save_pages(connection, page_records)
    save_segments(connection, segments)

    chunks = chunk_document(doc_record.doc_id, segments)
    save_chunks(connection, chunks)

    links = link_chunks(doc_record.doc_id, chunks, segments)
    save_chunk_links(connection, links)

    warnings: list[str] = []
    needs_ocr = sum(1 for p in page_records if p.needs_ocr)
    table_uncertain = sum(
        1 for p in page_records if p.parse_status is PageParseStatus.TABLE_UNCERTAIN
    )
    if needs_ocr:
        warnings.append(
            f"{manifest.source_id}: {needs_ocr} page(s) flagged NEEDS_OCR (S05 does not OCR)"
        )
    if table_uncertain:
        warnings.append(
            f"{manifest.source_id}: {table_uncertain} page(s) flagged TABLE_UNCERTAIN"
        )

    return IngestionSummary(
        document=doc_record,
        page_records=tuple(page_records),
        segment_records=tuple(segments),
        chunk_records=tuple(chunks),
        warnings=tuple(warnings),
    )


def ingest_corpus(
    connection: KnowledgeConnection,
    manifest: CorpusManifest,
    *,
    source_ids: Iterable[str] | None = None,
    validate_only: bool = False,
) -> IngestReport:
    """Ingest every (or selected) manifest entry, then write the snapshot."""

    requested = set(source_ids) if source_ids else None
    report = IngestReport(manifest=manifest)

    for entry in manifest.documents:
        if requested is not None and entry.source_id not in requested:
            continue
        try:
            summary = ingest_document(connection, entry, validate_only=validate_only)
        except KnowledgeConflict as exc:
            # Idempotent reruns of the same build are fine: re-running
            # the same ingest path must not silently drop the existing
            # rows. Surface the conflict so the operator can decide.
            report.warnings.append(f"{entry.source_id}: conflict ({exc})")
            continue
        report.summaries.append(summary)
        report.chunk_link_total += _link_count_for_summary(summary, link_chunks)

    snapshot = build_snapshot_record(manifest, report)
    if not validate_only:
        save_snapshot(connection, snapshot)

    return report


def build_snapshot_record(
    manifest: CorpusManifest,
    report: IngestReport,
) -> SnapshotRecord:
    """Materialize the BUILDING snapshot record for this run.

    Snapshot identity is bound to the manifest SHA + parser version +
    chunker version. The status field is always ``BUILDING`` here; S07
    is the only place that may flip it to ``READY``.
    """

    snapshot_id = derive_snapshot_id(
        corpus_id=manifest.corpus_id,
        manifest_sha256=manifest.manifest_sha256,
    )
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        corpus_id=manifest.corpus_id,
        manifest_sha256=manifest.manifest_sha256,
        knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION,
        parser_version=PARSER_VERSION,
        chunker_version=CHUNKER_VERSION,
        status=SNAPSHOT_STATUS_BUILDING,
        document_count=report.document_count,
        page_count=report.page_count,
        segment_count=report.segment_count,
        chunk_count=report.chunk_count,
        chunk_link_count=report.chunk_link_total,
        needs_ocr_pages=report.needs_ocr_pages,
        table_uncertain_pages=report.table_uncertain_pages,
        warnings=tuple(_collect_all_warnings(report)),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_document_record(
    manifest: ManifestDocument,
    sha256: str,
    page_count: int,
) -> DocumentRecord:
    doc_id = derive_doc_id(manifest.source_id, sha256)
    return DocumentRecord(
        doc_id=doc_id,
        source_id=manifest.source_id,
        corpus_id="s04-corpus-v1",
        source_url=manifest.source_url,
        sha256=sha256,
        document_revision=manifest.document_revision,
        document_type=manifest.document_type,
        language=manifest.language,
        local_file=manifest.local_file,
        page_count=page_count,
        document_reviewed=manifest.human_reviewed,
    )


def _build_page_records_and_segments(
    doc_id: str,
    parsed_pages: Sequence[object],
) -> tuple[list[PageRecord], list[object]]:
    page_records: list[PageRecord] = []
    segments: list = []
    for parsed in parsed_pages:
        status, hint = classify_page(parsed)
        page_id = f"{doc_id}:p{parsed.page_number:04d}"
        text = parsed.text or ""
        page_records.append(
            PageRecord(
                page_id=page_id,
                doc_id=doc_id,
                page_number=parsed.page_number,
                raw_text=text,
                text_char_count=len(text),
                image_count=parsed.image_count,
                parse_status=status,
                section_hint=hint,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
        segments.extend(segment_page(doc_id, parsed, status))
    return page_records, segments


def _link_count_for_summary(summary: IngestionSummary, linker) -> int:
    """Recompute the chunk-link count for one summary.

    We re-run the linker here because ``IngestionSummary`` does not
    carry the link list. This is acceptable: the link builder is pure
    and O(chunks × segments), and summaries are small in S05.
    """

    return len(linker(summary.document.doc_id, summary.chunk_records, summary.segment_records))


def _collect_all_warnings(report: IngestReport) -> list[str]:
    out: list[str] = list(report.warnings)
    for summary in report.summaries:
        out.extend(summary.warnings)
    return out
