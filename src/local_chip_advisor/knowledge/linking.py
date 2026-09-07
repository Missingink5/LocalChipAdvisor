"""Deterministic chunk-link builder for S05 ingestion.

S05 builds six kinds of intra-document links between :class:`ChunkRecord`
objects (see :class:`ChunkLinkKind`):

- ``PREVIOUS`` / ``NEXT`` between adjacent chunks in document order;
- ``PARENT_HEADING`` from a body chunk to the most recent heading chunk;
- ``TABLE_HEADER`` from a TABLE chunk to the most recent heading chunk;
- ``FOOTNOTE`` from a non-footnote chunk to a FOOTNOTE chunk on the
  same page (only when a clear footnote-like segment exists);
- ``CAPTION`` from a non-caption chunk to a CAPTION chunk on the same
  page (figure / table captions).

The linker never invents relations: if no confident heading or footnote
context exists for a chunk, no link of that kind is emitted. Building
links twice on identical inputs yields identical output (same primary
keys, same kind, same target).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .models import (
    ChunkLinkKind,
    ChunkLinkRecord,
    ChunkRecord,
    SegmentRecord,
    SegmentType,
)


def link_chunks(
    doc_id: str,
    chunks: Sequence[ChunkRecord],
    segments: Sequence[SegmentRecord],
) -> list[ChunkLinkRecord]:
    """Build intra-document links from chunks and their source segments.

    ``chunks`` must be in document order. ``segments`` must be in the
    same order the chunker consumed them (so that the segment-types
    inside each chunk can be recovered by membership matching on
    ``raw_text``).
    """

    if not chunks:
        return []

    chunk_segment_types = _segment_types_per_chunk(chunks, segments)

    links: list[ChunkLinkRecord] = []
    heading_chunk_index: int | None = None
    table_chunks_by_page: dict[int, list[int]] = {}
    footnote_chunks_by_page: dict[int, list[int]] = {}
    caption_chunks_by_page: dict[int, list[int]] = {}

    for index, chunk in enumerate(chunks):
        types = chunk_segment_types[index]
        page = chunk.page_start

        # PREVIOUS / NEXT
        if index > 0:
            links.append(_link(doc_id, chunk.chunk_id, chunks[index - 1].chunk_id, ChunkLinkKind.PREVIOUS))
        if index < len(chunks) - 1:
            links.append(_link(doc_id, chunk.chunk_id, chunks[index + 1].chunk_id, ChunkLinkKind.NEXT))

        # PARENT_HEADING
        if heading_chunk_index is not None and SegmentType.HEADING not in types:
            links.append(
                _link(
                    doc_id,
                    chunk.chunk_id,
                    chunks[heading_chunk_index].chunk_id,
                    ChunkLinkKind.PARENT_HEADING,
                )
            )

        # Track headings for subsequent chunks
        if SegmentType.HEADING in types:
            heading_chunk_index = index

        # TABLE_HEADER
        if SegmentType.TABLE in types:
            table_chunks_by_page.setdefault(page, []).append(index)
            if heading_chunk_index is not None and heading_chunk_index != index:
                links.append(
                    _link(
                        doc_id,
                        chunk.chunk_id,
                        chunks[heading_chunk_index].chunk_id,
                        ChunkLinkKind.TABLE_HEADER,
                    )
                )

        # FOOTNOTE
        if SegmentType.FOOTNOTE in types:
            footnote_chunks_by_page.setdefault(page, []).append(index)
        else:
            for footnote_index in footnote_chunks_by_page.get(page, []):
                if footnote_index != index:
                    links.append(
                        _link(
                            doc_id,
                            chunk.chunk_id,
                            chunks[footnote_index].chunk_id,
                            ChunkLinkKind.FOOTNOTE,
                        )
                    )

        # CAPTION
        if SegmentType.CAPTION in types:
            caption_chunks_by_page.setdefault(page, []).append(index)
        else:
            for caption_index in caption_chunks_by_page.get(page, []):
                if caption_index != index:
                    links.append(
                        _link(
                            doc_id,
                            chunk.chunk_id,
                            chunks[caption_index].chunk_id,
                            ChunkLinkKind.CAPTION,
                        )
                    )

    return _dedupe(links)


def _link(
    doc_id: str,
    source_chunk_id: str,
    target_chunk_id: str,
    kind: ChunkLinkKind,
) -> ChunkLinkRecord:
    return ChunkLinkRecord(
        source_chunk_id=source_chunk_id,
        target_chunk_id=target_chunk_id,
        kind=kind,
        doc_id=doc_id,
    )


def _segment_types_per_chunk(
    chunks: Sequence[ChunkRecord],
    segments: Sequence[SegmentRecord],
) -> list[set[SegmentType]]:
    """Return, for each chunk, the set of segment types it contains.

    The chunker concatenates segment raw_texts with newlines, so we can
    recover the membership by checking which segments' raw_text appears
    inside the chunk's raw_text. The matching is O(chunks*segments) but
    S05 document sizes are small (≤ ~300 pages) so this is acceptable.
    """

    types_per_chunk: list[set[SegmentType]] = []
    for chunk in chunks:
        types: set[SegmentType] = set()
        for segment in segments:
            if segment.raw_text.strip() and segment.raw_text.strip() in chunk.raw_text:
                types.add(segment.segment_type)
        types_per_chunk.append(types)
    return types_per_chunk


def _dedupe(links: Iterable[ChunkLinkRecord]) -> list[ChunkLinkRecord]:
    seen: set[tuple[str, str, ChunkLinkKind]] = set()
    out: list[ChunkLinkRecord] = []
    for link in links:
        key = (link.source_chunk_id, link.kind, link.target_chunk_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(link)
    return out
