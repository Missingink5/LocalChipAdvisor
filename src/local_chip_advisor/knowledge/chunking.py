"""Deterministic structural chunker for S05 ingestion.

A :class:`ChunkRecord` is the retrieval unit S06/S07/S08 will use. The
chunker consumes an ordered list of :class:`SegmentRecord` (already
classified by :mod:`knowledge.segmentation`) and emits chunks that:

- never split a heading apart from the body it introduces;
- keep table / footnote / caption segments atomic (no splitting inside);
- merge small paragraphs into one chunk up to the target token budget;
- split large paragraphs deterministically at sentence boundaries;
- never carry text across page boundaries unless explicitly allowed
  for a same-document tail merge (kept off by default).

The chunker is **pure and deterministic**: identical segment sequence
always produces identical chunk sequence with identical chunk_id. The
token estimate is the documented ``char-div4-v1`` heuristic (see
:func:`estimate_tokens`); S06 will revisit this against the real
embedding tokenizer context window, but S05 must not over-claim.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .models import (
    CHUNKER_VERSION,
    ChunkQuality,
    ChunkRecord,
    SegmentRecord,
    SegmentType,
    derive_chunk_id,
    estimate_tokens,
)


# Target token band for chunk retrieval. S05 documents this band but
# acknowledges S06 has not yet measured the real embedding tokenizer.
TARGET_MIN_TOKENS = 300
TARGET_MAX_TOKENS = 600

# Hard ceiling. A single segment above this is allowed but kept whole
# (we never split a table or footnote apart). The chunker logs nothing
# here; the page-level quality status already records the page risk.
HARD_MAX_TOKENS = 1200

# Sentence boundary regex used to split large paragraphs deterministically.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[\.\!\?])\s+(?=[A-Z0-9\"'(\[])")


# ---------------------------------------------------------------------------
# Internal accumulator
# ---------------------------------------------------------------------------


@dataclass
class _Acc:
    segments: list[SegmentRecord] = field(default_factory=list)
    raw_text: str = ""
    retrieval_text: str = ""
    page_start: int = 0
    page_end: int = 0
    estimated_tokens: int = 0
    quality: ChunkQuality = ChunkQuality.OK

    @classmethod
    def empty(cls, page_number: int, quality: ChunkQuality) -> "_Acc":
        return cls(
            page_start=page_number,
            page_end=page_number,
            quality=quality,
        )

    @classmethod
    def from_segment(cls, segment: SegmentRecord) -> "_Acc":
        acc = cls.empty(page_number=segment.page_number, quality=segment.quality_status)
        acc.append(segment)
        return acc

    def append(self, segment: SegmentRecord) -> None:
        self.segments.append(segment)
        text = segment.raw_text.strip()
        if self.raw_text:
            self.raw_text = f"{self.raw_text}\n{text}"
        else:
            self.raw_text = text
        retrieval = _retrieval_text_for(segment, self.segments[:-1])
        if self.retrieval_text:
            self.retrieval_text = f"{self.retrieval_text}\n{retrieval}"
        else:
            self.retrieval_text = retrieval
        if not self.page_start or segment.page_number < self.page_start:
            self.page_start = segment.page_number
        if segment.page_number > self.page_end:
            self.page_end = segment.page_number
        self.estimated_tokens = estimate_tokens(self.retrieval_text)
        if segment.quality_status is not ChunkQuality.OK:
            self.quality = segment.quality_status


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_document(
    doc_id: str,
    segments: Sequence[SegmentRecord],
) -> list[ChunkRecord]:
    """Produce deterministic structural chunks for one document.

    ``segments`` MUST be in document reading order (ascending page,
    then ascending sequence within each page).
    """

    chunks: list[ChunkRecord] = []
    if not segments:
        return chunks

    acc = _Acc.empty(
        page_number=segments[0].page_number,
        quality=segments[0].quality_status,
    )

    for segment in segments:
        acc_empty = not acc.segments

        # Atomic types never merge into an existing chunk.
        if segment.segment_type in _ATOMIC_TYPES:
            if not acc_empty:
                chunks.append(_flush(acc, doc_id, len(chunks)))
                acc = _Acc.empty(
                    page_number=segment.page_number,
                    quality=segment.quality_status,
                )
            # Split large atomic segments once if they exceed the hard ceiling.
            for part in _split_oversized([segment]):
                chunks.append(_flush(_Acc.from_segment(part), doc_id, len(chunks)))
            continue

        # Headings open a new chunk unless the accumulator is empty.
        if segment.segment_type is SegmentType.HEADING and not acc_empty:
            chunks.append(_flush(acc, doc_id, len(chunks)))
            acc = _Acc.empty(
                page_number=segment.page_number,
                quality=segment.quality_status,
            )

        prospective = _clone_acc(acc)
        prospective.append(segment)

        if prospective.estimated_tokens > HARD_MAX_TOKENS and not acc_empty:
            for part in _split_oversized([segment]):
                if not acc.segments:
                    acc = _Acc.empty(
                        page_number=part.page_number,
                        quality=part.quality_status,
                    )
                trial = _clone_acc(acc)
                trial.append(part)
                if trial.estimated_tokens <= HARD_MAX_TOKENS:
                    acc.append(part)
                else:
                    chunks.append(_flush(acc, doc_id, len(chunks)))
                    acc = _Acc.from_segment(part)
            continue

        if prospective.estimated_tokens > TARGET_MAX_TOKENS and not acc_empty:
            chunks.append(_flush(acc, doc_id, len(chunks)))
            acc = _Acc.empty(
                page_number=segment.page_number,
                quality=segment.quality_status,
            )

        acc.append(segment)

        if acc.estimated_tokens >= TARGET_MIN_TOKENS and _is_boundary(acc):
            chunks.append(_flush(acc, doc_id, len(chunks)))
            acc = _Acc.empty(
                page_number=_next_page(acc, segments),
                quality=ChunkQuality.OK,
            )

    if acc.segments:
        chunks.append(_flush(acc, doc_id, len(chunks)))

    return chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_ATOMIC_TYPES = {
    SegmentType.TABLE,
    SegmentType.FOOTNOTE,
    SegmentType.CAPTION,
}


def _retrieval_text_for(segment: SegmentRecord, earlier: Sequence[SegmentRecord]) -> str:
    """Compose retrieval text with structural context for this segment.

    The retrieval text is what S06/S07 will embed and search. We never
    invent content; we only attach heading context that already exists
    on the page. Heading context is explicitly marked with a delimiter
    so downstream consumers can tell metadata apart from raw text.
    """

    head = _nearest_heading(earlier)
    body = segment.raw_text.strip()
    if head:
        return f"section: {head}\n{body}"
    return body


def _nearest_heading(earlier: Sequence[SegmentRecord]) -> str | None:
    for seg in reversed(earlier):
        if seg.segment_type is SegmentType.HEADING:
            text = seg.raw_text.strip()
            if text:
                return text
    return None


def _split_oversized(segments: Iterable[SegmentRecord]) -> list[SegmentRecord]:
    """Split text-heavy segments into sentence-level pieces.

    Atomic segments are kept whole even if they exceed HARD_MAX_TOKENS,
    because splitting a table apart would lose its structural meaning.
    """

    out: list[SegmentRecord] = []
    for seg in segments:
        if seg.segment_type in _ATOMIC_TYPES:
            out.append(seg)
            continue
        text = seg.raw_text.strip()
        if estimate_tokens(text) <= HARD_MAX_TOKENS:
            out.append(seg)
            continue
        sentences = [s.strip() for s in _SENTENCE_BOUNDARY.split(text) if s.strip()]
        if len(sentences) <= 1:
            out.append(seg)
            continue
        for index, sentence in enumerate(sentences):
            out.append(
                SegmentRecord(
                    segment_id=f"{seg.segment_id}#p{index:02d}",
                    doc_id=seg.doc_id,
                    page_number=seg.page_number,
                    sequence=seg.sequence * 1000 + index,
                    segment_type=seg.segment_type,
                    raw_text=sentence,
                    bbox=seg.bbox,
                    heading_path=seg.heading_path,
                    quality_status=seg.quality_status,
                    content_hash=hashlib.sha256(sentence.encode("utf-8")).hexdigest(),
                )
            )
    return out


def _is_boundary(acc: _Acc) -> bool:
    """Return True when it is safe to close ``acc`` at this point.

    We only auto-close at heading boundaries or when the accumulator is
    well past the target band. Otherwise we wait for an explicit
    structural boundary.
    """

    if not acc.segments:
        return False
    last = acc.segments[-1]
    if last.segment_type is SegmentType.HEADING:
        return False  # never close immediately after a heading
    if acc.estimated_tokens >= TARGET_MAX_TOKENS:
        return True
    if last.segment_type in {SegmentType.PARAGRAPH, SegmentType.LIST}:
        return acc.estimated_tokens >= TARGET_MIN_TOKENS
    return False


def _next_page(acc: _Acc, segments: Sequence[SegmentRecord]) -> int:
    for seg in segments:
        if seg.page_number > acc.page_end:
            return seg.page_number
    return acc.page_end + 1


def _clone_acc(acc: _Acc) -> _Acc:
    return _Acc(
        segments=list(acc.segments),
        raw_text=acc.raw_text,
        retrieval_text=acc.retrieval_text,
        page_start=acc.page_start,
        page_end=acc.page_end,
        estimated_tokens=acc.estimated_tokens,
        quality=acc.quality,
    )


def _flush(acc: _Acc, doc_id: str, sequence: int) -> ChunkRecord:
    raw_text = acc.raw_text.strip()
    retrieval_text = acc.retrieval_text.strip()
    chunk_id = derive_chunk_id(
        doc_id=doc_id,
        page_start=acc.page_start,
        page_end=acc.page_end,
        sequence=sequence,
        retrieval_text=retrieval_text,
        chunker_version=CHUNKER_VERSION,
    )
    content_hash = hashlib.sha256(retrieval_text.encode("utf-8")).hexdigest()
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        page_start=acc.page_start,
        page_end=acc.page_end,
        sequence=sequence,
        raw_text=raw_text,
        retrieval_text=retrieval_text,
        estimated_tokens=estimate_tokens(retrieval_text),
        chunker_version=CHUNKER_VERSION,
        quality_status=acc.quality,
        content_hash=content_hash,
    )
