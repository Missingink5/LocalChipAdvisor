"""Local knowledge repository package.

S05 introduces a second storage tier beside the published product catalog.
The two stores are independent files; nothing in this package imports from
:mod:`local_chip_advisor.catalog` and no foreign keys cross the boundary.

Layering inside this package:

- :mod:`models` owns value objects and stable ID derivation.
- :mod:`repository` owns the SQLite schema and read/write API.
- :mod:`quality` owns deterministic page-quality classification.
- :mod:`chunking` owns structural segment + chunk extraction (added in S05.5+).
- :mod:`ingest` owns the manifest-driven pipeline that ties parsing,
  segmenting, chunking, and persistence together (added in S05.8).
"""

from __future__ import annotations

from .models import (
    CHUNKER_VERSION,
    KNOWLEDGE_SCHEMA_VERSION,
    PARSER_VERSION,
    SNAPSHOT_STATUS_BUILDING,
    ChunkLinkKind,
    ChunkLinkRecord,
    ChunkQuality,
    ChunkRecord,
    DocumentProductLink,
    DocumentRecord,
    GoldSpanCoverage,
    IngestionSummary,
    PageParseStatus,
    PageRecord,
    SegmentRecord,
    SegmentType,
    SnapshotRecord,
    derive_chunk_id,
    derive_doc_id,
    derive_page_id,
    derive_segment_id,
    derive_snapshot_id,
    estimate_tokens,
)
from .quality import (
    IMAGE_HEAVY_BLOCK_RATIO,
    LOW_TEXT_CHAR_THRESHOLD,
    classify_page,
)
from .segmentation import segment_page, segment_pages
from .chunking import (
    HARD_MAX_TOKENS,
    TARGET_MAX_TOKENS,
    TARGET_MIN_TOKENS,
    chunk_document,
)
from .linking import link_chunks
from .ingest import (
    CorpusManifest,
    HashMismatchError,
    IngestError,
    IngestReport,
    ManifestDocument,
    PageCountMismatchError,
    build_snapshot_record,
    ingest_corpus,
    ingest_document,
    load_corpus_manifest,
)
from .repository import (
    KnowledgeConflict,
    KnowledgeConnection,
    KnowledgeError,
    KnowledgeSchemaError,
    compute_manifest_sha256,
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

__all__ = [
    "CHUNKER_VERSION",
    "ChunkLinkKind",
    "ChunkLinkRecord",
    "ChunkQuality",
    "ChunkRecord",
    "CorpusManifest",
    "HARD_MAX_TOKENS",
    "HashMismatchError",
    "TARGET_MAX_TOKENS",
    "TARGET_MIN_TOKENS",
    "build_snapshot_record",
    "chunk_document",
    "DocumentProductLink",
    "DocumentRecord",
    "GoldSpanCoverage",
    "IMAGE_HEAVY_BLOCK_RATIO",
    "IngestError",
    "IngestReport",
    "IngestionSummary",
    "KNOWLEDGE_SCHEMA_VERSION",
    "KnowledgeConflict",
    "KnowledgeConnection",
    "KnowledgeError",
    "KnowledgeSchemaError",
    "LOW_TEXT_CHAR_THRESHOLD",
    "ManifestDocument",
    "PARSER_VERSION",
    "PageCountMismatchError",
    "PageParseStatus",
    "PageRecord",
    "SNAPSHOT_STATUS_BUILDING",
    "SegmentRecord",
    "SegmentType",
    "SnapshotRecord",
    "classify_page",
    "compute_manifest_sha256",
    "derive_chunk_id",
    "derive_doc_id",
    "derive_page_id",
    "derive_segment_id",
    "derive_snapshot_id",
    "estimate_tokens",
    "initialize_knowledge_database",
    "ingest_corpus",
    "ingest_document",
    "list_chunk_links_for_document",
    "list_chunks_for_document",
    "list_document_product_links",
    "list_documents",
    "list_pages_for_document",
    "list_snapshots",
    "link_chunks",
    "load_chunk",
    "load_corpus_manifest",
    "load_document",
    "load_page",
    "open_knowledge_database",
    "save_chunk_links",
    "save_chunks",
    "save_document",
    "save_pages",
    "save_segments",
    "save_snapshot",
    "segment_page",
    "segment_pages",
    "verify_known_tables",
]
