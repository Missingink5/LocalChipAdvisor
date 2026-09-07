"""Domain models for the local knowledge repository.

S05 introduces a second storage tier beside the published product catalog.
This module owns the value objects that flow through parsing, segmenting,
chunking, and snapshot construction. Every identifier is derived from
stable content hashes so that retried builds and SHA-preserving edits
remain idempotent.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# Versioning constants. Bumping these on a behavior change forces new
# chunk identity even when raw text remains identical. Dates are recorded
# separately by the build pipeline; they are never part of the identity.
PARSER_VERSION = "pdf-parser-v2"
CHUNKER_VERSION = "structure-chunker-v1"
TOKEN_ESTIMATOR_VERSION = "char-div4-v1"
KNOWLEDGE_SCHEMA_VERSION = 1
SNAPSHOT_STATUS_BUILDING = "BUILDING"


class PageParseStatus(StrEnum):
    """Diagnostic label for how well a page was extracted.

    These labels describe extraction quality, never product claims.
    """

    OK = "OK"
    LOW_TEXT = "LOW_TEXT"
    NEEDS_OCR = "NEEDS_OCR"
    TABLE_UNCERTAIN = "TABLE_UNCERTAIN"
    IMAGE_HEAVY = "IMAGE_HEAVY"
    PARSE_ERROR = "PARSE_ERROR"


class SegmentType(StrEnum):
    """Coarse structural classification for one segment on a page."""

    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    TABLE = "TABLE"
    FOOTNOTE = "FOOTNOTE"
    CAPTION = "CAPTION"
    LIST = "LIST"
    OTHER = "OTHER"


class ChunkQuality(StrEnum):
    """Quality label propagated from page diagnostics onto chunks."""

    OK = "OK"
    LOW_TEXT = "LOW_TEXT"
    NEEDS_OCR = "NEEDS_OCR"
    TABLE_UNCERTAIN = "TABLE_UNCERTAIN"
    IMAGE_HEAVY = "IMAGE_HEAVY"
    PARSE_ERROR = "PARSE_ERROR"


class ChunkLinkKind(StrEnum):
    """Deterministic structural relations between chunks."""

    PREVIOUS = "PREVIOUS"
    NEXT = "NEXT"
    PARENT_HEADING = "PARENT_HEADING"
    TABLE_HEADER = "TABLE_HEADER"
    FOOTNOTE = "FOOTNOTE"
    CAPTION = "CAPTION"


_SAFE_ID_PATTERN = re.compile(r"[^a-z0-9._:-]+")


def _normalize_source_id(source_id: str) -> str:
    cleaned = _SAFE_ID_PATTERN.sub("-", source_id.strip().lower())
    cleaned = cleaned.strip("-")
    if not cleaned:
        raise ValueError(f"source_id cannot be normalized: {source_id!r}")
    return cleaned


def _sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def derive_doc_id(source_id: str, sha256: str) -> str:
    """Derive a stable document identifier from ``source_id`` and content hash."""

    if not source_id:
        raise ValueError("source_id must not be empty")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise ValueError("sha256 must be 64 hexadecimal characters")
    return f"doc:{_normalize_source_id(source_id)}:{sha256.lower()[:12]}"


def derive_page_id(doc_id: str, page_number: int) -> str:
    """Derive a stable per-page identifier."""

    if page_number < 1:
        raise ValueError("page_number must be >= 1")
    return f"{doc_id}:p{page_number:04d}"


def derive_segment_id(
    doc_id: str,
    page_number: int,
    sequence: int,
    *,
    parser_version: str = PARSER_VERSION,
) -> str:
    """Derive a stable per-segment identifier."""

    if sequence < 0:
        raise ValueError("sequence must be >= 0")
    return f"{doc_id}:p{page_number:04d}:s{sequence:04d}:{parser_version}"


def derive_chunk_id(
    *,
    doc_id: str,
    page_start: int,
    page_end: int,
    sequence: int,
    retrieval_text: str,
    chunker_version: str = CHUNKER_VERSION,
) -> str:
    """Derive a stable chunk identifier from provenance plus content."""

    if page_start < 1:
        raise ValueError("page_start must be >= 1")
    if page_end < page_start:
        raise ValueError("page_end must be >= page_start")
    if sequence < 0:
        raise ValueError("sequence must be >= 0")
    content_digest = _sha256_hex(retrieval_text)[:16]
    return (
        f"chunk:{doc_id}:{page_start:04d}-{page_end:04d}:"
        f"seq{sequence:04d}:{chunker_version}:{content_digest}"
    )


def derive_snapshot_id(
    *,
    corpus_id: str,
    manifest_sha256: str,
    parser_version: str = PARSER_VERSION,
    chunker_version: str = CHUNKER_VERSION,
) -> str:
    """Derive a deterministic build/snapshot identifier."""

    material = (
        f"{corpus_id}|{manifest_sha256.lower()}|{parser_version}|{chunker_version}"
    )
    digest = _sha256_hex(material)[:16]
    return f"build:{corpus_id}:{digest}"


def estimate_tokens(text: str) -> int:
    """Deterministic, conservative token estimate.

    S05 must not claim exact tokenizer parity. ``char-div4-v1`` is a
    well-documented heuristic and is reported alongside the estimate so
    later S06 verification can replace it without changing the chunker.
    """

    cleaned = text.strip()
    if not cleaned:
        return 0
    return (len(cleaned) + 3) // 4


@dataclass(frozen=True)
class DocumentRecord:
    """A registered source document with provenance and identity."""

    doc_id: str
    source_id: str
    corpus_id: str
    source_url: str
    sha256: str
    document_revision: str
    document_type: str
    language: str
    local_file: Path
    page_count: int
    document_reviewed: bool


@dataclass(frozen=True)
class DocumentProductLink:
    """Document-level binding to one product id covered by the datasheet."""

    doc_id: str
    product_id: str


@dataclass(frozen=True)
class PageRecord:
    """Parsed page with raw text and quality diagnostics."""

    page_id: str
    doc_id: str
    page_number: int
    raw_text: str
    text_char_count: int
    image_count: int
    parse_status: PageParseStatus
    section_hint: str | None
    content_hash: str

    @property
    def is_image_heavy(self) -> bool:
        return self.parse_status is PageParseStatus.IMAGE_HEAVY

    @property
    def needs_ocr(self) -> bool:
        return self.parse_status is PageParseStatus.NEEDS_OCR


@dataclass(frozen=True)
class SegmentRecord:
    """One structural segment on a page."""

    segment_id: str
    doc_id: str
    page_number: int
    sequence: int
    segment_type: SegmentType
    raw_text: str
    bbox: tuple[float, float, float, float] | None
    heading_path: tuple[str, ...]
    quality_status: ChunkQuality
    content_hash: str


@dataclass(frozen=True)
class ChunkRecord:
    """One retrieval unit: structural chunk with raw and retrieval text."""

    chunk_id: str
    doc_id: str
    page_start: int
    page_end: int
    sequence: int
    raw_text: str
    retrieval_text: str
    estimated_tokens: int
    chunker_version: str
    quality_status: ChunkQuality
    content_hash: str


@dataclass(frozen=True)
class ChunkLinkRecord:
    """Directed relation from one chunk to another."""

    source_chunk_id: str
    target_chunk_id: str
    kind: ChunkLinkKind
    doc_id: str


@dataclass(frozen=True)
class SnapshotRecord:
    """Build identity plus BUILDING status; READY activation is S07's job."""

    snapshot_id: str
    corpus_id: str
    manifest_sha256: str
    knowledge_schema_version: int
    parser_version: str
    chunker_version: str
    status: str
    document_count: int
    page_count: int
    segment_count: int
    chunk_count: int
    chunk_link_count: int
    needs_ocr_pages: int
    table_uncertain_pages: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IngestionSummary:
    """Per-document summary returned by the ingest pipeline."""

    document: DocumentRecord
    page_records: tuple[PageRecord, ...]
    segment_records: tuple[SegmentRecord, ...]
    chunk_records: tuple[ChunkRecord, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GoldSpanCoverage:
    """Mapping of one gold span to the chunks that contain its verbatim text."""

    gold_span_id: str
    source_id: str
    source_sha256: str
    page: int
    chunk_ids: tuple[str, ...]
    coverage_status: str  # COMPLETE | MULTI_CHUNK | MISSING