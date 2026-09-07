"""Contract tests for the deterministic chunk-link builder."""

from __future__ import annotations

import hashlib

from local_chip_advisor.knowledge import (
    CHUNKER_VERSION,
    ChunkLinkKind,
    ChunkQuality,
    ChunkRecord,
    SegmentRecord,
    SegmentType,
    chunk_document,
    link_chunks,
)


def _segment(
    doc_id: str,
    page_number: int,
    sequence: int,
    text: str,
    *,
    segment_type: SegmentType = SegmentType.PARAGRAPH,
) -> SegmentRecord:
    return SegmentRecord(
        segment_id=f"{doc_id}:p{page_number:04d}:s{sequence:04d}:{CHUNKER_VERSION}",
        doc_id=doc_id,
        page_number=page_number,
        sequence=sequence,
        segment_type=segment_type,
        raw_text=text,
        bbox=None,
        heading_path=(),
        quality_status=ChunkQuality.OK,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _build_chunks_and_segments() -> tuple[list[ChunkRecord], list[SegmentRecord]]:
    doc_id = "doc:test:abcdabcdabcd"
    segments = [
        _segment(doc_id, 1, 0, "ABSOLUTE MAXIMUM RATINGS", segment_type=SegmentType.HEADING),
        _segment(
            doc_id,
            1,
            1,
            "PARAMETER CONDITIONS MIN TYP MAX UNIT\nVin 4.5 55 V",
            segment_type=SegmentType.TABLE,
        ),
        _segment(doc_id, 1, 2, "Body paragraph follows the table."),
        _segment(
            doc_id,
            1,
            3,
            "* Note: typical values measured at 25C.",
            segment_type=SegmentType.FOOTNOTE,
        ),
        _segment(doc_id, 2, 0, "FUNCTIONAL DESCRIPTION", segment_type=SegmentType.HEADING),
        _segment(doc_id, 2, 1, "The MP4570 integrates low RDSon MOSFETs."),
    ]
    chunks = chunk_document(doc_id, segments)
    return chunks, segments


def test_link_chunks_returns_empty_list_for_no_chunks() -> None:
    assert link_chunks("doc:test:abcdabcdabcd", [], []) == []


def test_link_chunks_emits_previous_and_next_between_adjacent_chunks() -> None:
    chunks, segments = _build_chunks_and_segments()

    links = link_chunks("doc:test:abcdabcdabcd", chunks, segments)

    kinds = {(link.source_chunk_id, link.kind) for link in links}
    for index in range(len(chunks) - 1):
        assert (chunks[index].chunk_id, ChunkLinkKind.NEXT) in kinds
        assert (chunks[index + 1].chunk_id, ChunkLinkKind.PREVIOUS) in kinds


def test_link_chunks_attaches_table_to_parent_heading() -> None:
    chunks, segments = _build_chunks_and_segments()

    links = link_chunks("doc:test:abcdabcdabcd", chunks, segments)

    table_header_links = [
        link for link in links if link.kind is ChunkLinkKind.TABLE_HEADER
    ]
    assert table_header_links, "expected at least one TABLE_HEADER link"
    for link in table_header_links:
        assert link.doc_id == "doc:test:abcdabcdabcd"


def test_link_chunks_attaches_footnote_on_same_page() -> None:
    chunks, segments = _build_chunks_and_segments()

    links = link_chunks("doc:test:abcdabcdabcd", chunks, segments)

    footnote_links = [link for link in links if link.kind is ChunkLinkKind.FOOTNOTE]
    # There is at least one body chunk on page 1 that should be linked
    # to the footnote chunk on the same page.
    assert footnote_links


def test_link_chunks_is_idempotent() -> None:
    chunks, segments = _build_chunks_and_segments()

    first = link_chunks("doc:test:abcdabcdabcd", chunks, segments)
    second = link_chunks("doc:test:abcdabcdabcd", chunks, segments)

    assert [(l.source_chunk_id, l.kind, l.target_chunk_id) for l in first] == [
        (l.source_chunk_id, l.kind, l.target_chunk_id) for l in second
    ]


def test_link_chunks_emits_parent_heading_for_body_chunk() -> None:
    chunks, segments = _build_chunks_and_segments()

    links = link_chunks("doc:test:abcdabcdabcd", chunks, segments)

    parent_links = [link for link in links if link.kind is ChunkLinkKind.PARENT_HEADING]
    assert parent_links


def test_link_chunks_does_not_cross_documents() -> None:
    chunks, segments = _build_chunks_and_segments()

    links = link_chunks("doc:test:abcdabcdabcd", chunks, segments)

    # All links belong to the same doc; the test ensures no foreign doc_id leaks.
    for link in links:
        assert link.doc_id == "doc:test:abcdabcdabcd"
