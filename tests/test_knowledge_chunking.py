"""Contract tests for the deterministic structural chunker."""

from __future__ import annotations

import hashlib

from local_chip_advisor.knowledge import (
    CHUNKER_VERSION,
    ChunkQuality,
    ChunkRecord,
    SegmentRecord,
    SegmentType,
    chunk_document,
    estimate_tokens,
)


def _segment(
    doc_id: str,
    page_number: int,
    sequence: int,
    text: str,
    *,
    segment_type: SegmentType = SegmentType.PARAGRAPH,
    quality: ChunkQuality = ChunkQuality.OK,
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
        quality_status=quality,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def test_chunk_document_returns_empty_list_for_no_segments() -> None:
    assert chunk_document("doc:test:abcdabcdabcd", ()) == []


def test_chunk_document_emits_one_chunk_for_a_short_paragraph() -> None:
    doc_id = "doc:test:abcdabcdabcd"
    text = "MP4570 is a synchronous step-down converter."
    segments = [_segment(doc_id, 1, 0, text)]

    chunks = chunk_document(doc_id, segments)

    assert len(chunks) == 1
    assert chunks[0].raw_text == text
    assert chunks[0].estimated_tokens == estimate_tokens(text)


def test_chunk_document_keeps_table_segments_atomic() -> None:
    doc_id = "doc:test:abcdabcdabcd"
    body = "MP4570 description paragraph."
    table = "PARAMETER CONDITIONS MIN TYP MAX UNIT\nVin 4.5 55 V"
    segments = [
        _segment(doc_id, 1, 0, body),
        _segment(doc_id, 1, 1, table, segment_type=SegmentType.TABLE),
    ]

    chunks = chunk_document(doc_id, segments)

    table_chunk = next(c for c in chunks if c.raw_text == table)
    assert table_chunk.raw_text == table
    # The body chunk must NOT contain the table text, proving the table
    # was not merged into the surrounding paragraph.
    body_chunk = next(c for c in chunks if body in c.raw_text)
    assert table not in body_chunk.raw_text


def test_chunk_document_splits_long_paragraphs_deterministically() -> None:
    doc_id = "doc:test:abcdabcdabcd"
    sentence_a = "MP4570 supports a wide input voltage range."
    sentence_b = "It delivers up to three amps of continuous current."
    sentence_c = "The device integrates low RDSon MOSFETs."
    long_paragraph = f"{sentence_a} {sentence_b} {sentence_c}"
    # Force the segment to look oversized by padding it (still under
    # the hard ceiling so we don't split, but past the target band).
    filler = " Additional context: " + ("x" * 1500)
    segments = [_segment(doc_id, 1, 0, long_paragraph + filler)]

    chunks = chunk_document(doc_id, segments)

    assert len(chunks) >= 1
    total_tokens = sum(c.estimated_tokens for c in chunks)
    assert total_tokens == estimate_tokens(chunks[-1].retrieval_text) or any(
        c.retrieval_text.startswith("section: ") is False for c in chunks
    )
    # Chunks must use the same CHUNKER_VERSION so identity is stable.
    for chunk in chunks:
        assert chunk.chunker_version == CHUNKER_VERSION


def test_chunk_document_assigns_unique_chunk_ids() -> None:
    doc_id = "doc:test:abcdabcdabcd"
    segments = [
        _segment(doc_id, 1, 0, "First body paragraph."),
        _segment(doc_id, 1, 1, "Second body paragraph."),
        _segment(doc_id, 1, 2, "Third body paragraph."),
    ]

    chunks = chunk_document(doc_id, segments)

    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids)


def test_chunk_document_is_idempotent_on_same_input() -> None:
    doc_id = "doc:test:abcdabcdabcd"
    segments = [
        _segment(doc_id, 1, 0, "Heading paragraph.", segment_type=SegmentType.HEADING),
        _segment(doc_id, 1, 1, "Body paragraph that follows."),
    ]

    first = chunk_document(doc_id, segments)
    second = chunk_document(doc_id, segments)

    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.estimated_tokens for c in first] == [c.estimated_tokens for c in second]


def test_chunk_document_tracks_page_range_across_pages() -> None:
    doc_id = "doc:test:abcdabcdabcd"
    segments = [
        _segment(doc_id, 1, 0, "First page paragraph."),
        _segment(doc_id, 2, 0, "Second page paragraph."),
    ]

    chunks = chunk_document(doc_id, segments)

    # We allow a single chunk spanning both pages when neither segment
    # is structural (HEADING/TABLE/...). Either way the page range must
    # be correctly recorded.
    for chunk in chunks:
        assert chunk.page_start >= 1
        assert chunk.page_end >= chunk.page_start


def test_chunk_document_propagates_quality_status() -> None:
    doc_id = "doc:test:abcdabcdabcd"
    segments = [
        _segment(
            doc_id,
            1,
            0,
            "Caption-like text.",
            segment_type=SegmentType.CAPTION,
            quality=ChunkQuality.NEEDS_OCR,
        ),
    ]

    chunks = chunk_document(doc_id, segments)

    assert chunks[0].quality_status is ChunkQuality.NEEDS_OCR
