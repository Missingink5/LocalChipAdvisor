"""Contract tests for knowledge-domain value objects and ID derivation."""

from __future__ import annotations

import pytest

from local_chip_advisor.knowledge.models import (
    KNOWLEDGE_SCHEMA_VERSION,
    PARSER_VERSION,
    SNAPSHOT_STATUS_BUILDING,
    ChunkLinkKind,
    ChunkQuality,
    SegmentType,
    derive_chunk_id,
    derive_doc_id,
    derive_page_id,
    derive_segment_id,
    derive_snapshot_id,
    estimate_tokens,
)


def test_derive_doc_id_is_stable_and_normalises_source_id() -> None:
    doc_id = derive_doc_id("mps-mp4570-datasheet", "A" * 64)

    assert doc_id == "doc:mps-mp4570-datasheet:aaaaaaaaaaaa"


def test_derive_doc_id_changes_when_sha_changes() -> None:
    first = derive_doc_id(
        "mps-mp4570-datasheet",
        "A" * 64,
    )
    second = derive_doc_id(
        "mps-mp4570-datasheet",
        "B" * 64,
    )

    assert first != second


def test_derive_doc_id_rejects_empty_source_id() -> None:
    with pytest.raises(ValueError, match="source_id"):
        derive_doc_id("", "A" * 64)


def test_derive_doc_id_rejects_non_hex_sha() -> None:
    with pytest.raises(ValueError, match="sha256"):
        derive_doc_id("mps", "Z" * 64)


def test_derive_page_id_uses_zero_padded_physical_page() -> None:
    page_id = derive_page_id("doc:mps:abc", 7)

    assert page_id == "doc:mps:abc:p0007"


def test_derive_page_id_rejects_non_positive_page() -> None:
    with pytest.raises(ValueError):
        derive_page_id("doc:mps:abc", 0)


def test_derive_segment_id_binds_parser_version() -> None:
    segment_id = derive_segment_id("doc:mps:abc", 12, 4)

    assert segment_id == f"doc:mps:abc:p0012:s0004:{PARSER_VERSION}"


def test_derive_segment_id_rejects_negative_sequence() -> None:
    with pytest.raises(ValueError):
        derive_segment_id("doc:mps:abc", 1, -1)


def test_derive_chunk_id_is_deterministic_on_same_inputs() -> None:
    first = derive_chunk_id(
        doc_id="doc:mps:abc",
        page_start=3,
        page_end=5,
        sequence=2,
        retrieval_text="hello world",
    )
    second = derive_chunk_id(
        doc_id="doc:mps:abc",
        page_start=3,
        page_end=5,
        sequence=2,
        retrieval_text="hello world",
    )

    assert first == second


def test_derive_chunk_id_changes_when_text_changes() -> None:
    base = derive_chunk_id(
        doc_id="doc:mps:abc",
        page_start=3,
        page_end=5,
        sequence=2,
        retrieval_text="hello world",
    )
    changed = derive_chunk_id(
        doc_id="doc:mps:abc",
        page_start=3,
        page_end=5,
        sequence=2,
        retrieval_text="hello WORLD",
    )

    assert base != changed


def test_derive_chunk_id_changes_when_chunker_version_changes() -> None:
    base = derive_chunk_id(
        doc_id="doc:mps:abc",
        page_start=3,
        page_end=5,
        sequence=2,
        retrieval_text="hello",
    )
    other = derive_chunk_id(
        doc_id="doc:mps:abc",
        page_start=3,
        page_end=5,
        sequence=2,
        retrieval_text="hello",
        chunker_version="structure-chunker-v2",
    )

    assert base != other


def test_derive_chunk_id_rejects_invalid_page_range() -> None:
    with pytest.raises(ValueError):
        derive_chunk_id(
            doc_id="doc:mps:abc",
            page_start=5,
            page_end=3,
            sequence=0,
            retrieval_text="x",
        )


def test_derive_snapshot_id_is_deterministic() -> None:
    first = derive_snapshot_id(
        corpus_id="s04-corpus-v1",
        manifest_sha256="A" * 64,
    )
    second = derive_snapshot_id(
        corpus_id="s04-corpus-v1",
        manifest_sha256="A" * 64,
    )

    assert first == second
    assert first.startswith("build:s04-corpus-v1:")


def test_derive_snapshot_id_changes_with_parser_version() -> None:
    base = derive_snapshot_id(corpus_id="c", manifest_sha256="A" * 64)
    other = derive_snapshot_id(
        corpus_id="c",
        manifest_sha256="A" * 64,
        parser_version="pdf-parser-v9",
    )

    assert base != other


def test_derive_snapshot_id_changes_with_chunker_version() -> None:
    base = derive_snapshot_id(
        corpus_id="c",
        manifest_sha256="A" * 64,
    )
    other = derive_snapshot_id(
        corpus_id="c",
        manifest_sha256="A" * 64,
        chunker_version="structure-chunker-v9",
    )

    assert base != other


def test_estimate_tokens_uses_documented_heuristic() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("a" * 400) == 100


def test_schema_and_parser_versions_are_frozen() -> None:
    assert KNOWLEDGE_SCHEMA_VERSION == 1
    assert PARSER_VERSION == "pdf-parser-v2"
    assert SNAPSHOT_STATUS_BUILDING == "BUILDING"


def test_segment_and_chunk_enums_cover_minimum_set() -> None:
    assert {t.value for t in SegmentType} >= {
        "HEADING",
        "PARAGRAPH",
        "TABLE",
        "FOOTNOTE",
        "CAPTION",
        "LIST",
        "OTHER",
    }
    assert {c.value for c in ChunkQuality} >= {
        "OK",
        "LOW_TEXT",
        "NEEDS_OCR",
        "TABLE_UNCERTAIN",
        "IMAGE_HEAVY",
        "PARSE_ERROR",
    }
    assert {k.value for k in ChunkLinkKind} >= {
        "PREVIOUS",
        "NEXT",
        "PARENT_HEADING",
        "TABLE_HEADER",
        "FOOTNOTE",
        "CAPTION",
    }


def test_doc_id_path_does_not_break_on_unicode_source_ids() -> None:
    doc_id = derive_doc_id("中文-source", "B" * 64)

    # Non-ASCII source_ids normalise to safe ASCII but must remain stable.
    again = derive_doc_id("中文-source", "B" * 64)
    assert doc_id == again
    assert doc_id.startswith("doc:")
