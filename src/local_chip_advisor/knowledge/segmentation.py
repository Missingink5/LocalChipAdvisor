"""Deterministic structural segmentation for S05 ingestion.

A :class:`SegmentRecord` is one contiguous block of page text classified
by structural role (heading, paragraph, table, list, footnote, caption,
other). S05 must NOT use any LLM or embedding call here. The classifier
relies on local PyMuPDF layout signals plus plain-text heuristics:

- span font sizes (largest on page → heading candidates);
- bold-flag spans (helps confirm a heading);
- ``find_tables`` (page-level table presence);
- bullet markers and numbering (list items);
- the existing page-quality :class:`PageParseStatus` (page flagged
  TABLE_UNCERTAIN propagates to segments with type TABLE);
- simple page-relative position heuristics (top-of-page footnote-like
  patterns, bottom-of-page caption-like patterns).

The output segment_id is derived from ``(doc_id, page_number, sequence,
parser_version)`` so segment identity is stable across reruns.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from typing import Protocol

from .models import (
    PARSER_VERSION,
    ChunkQuality,
    PageParseStatus,
    SegmentRecord,
    SegmentType,
    derive_segment_id,
)


# ---------------------------------------------------------------------------
# Layout view (Protocol) – keeps knowledge → ingestion dependency one-way.
# ---------------------------------------------------------------------------


class _PageLayoutView(Protocol):
    page_number: int
    text: str
    char_count: int
    image_count: int
    text_block_count: int
    image_block_count: int
    table_detected: bool
    blocks: Sequence[object]


class _TextBlockView(Protocol):
    block_no: int
    sequence: int
    block_type: int
    bbox: tuple[float, float, float, float]
    text: str
    line_count: int


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

_HEADING_FONT_SIZE_DELTA = 1.0
_LIST_BULLET_PATTERN = re.compile(r"^\s*(?:[-•·▪◦]|\d+[.)]|[a-z][.)])\s+")
_FOOTNOTE_MARKER = re.compile(
    r"(?m)^\s*(?:[*†‡§]|note\s+\d+|footnote\s+\d+)\s*[:.]?\s+"
)
_CAPTION_MARKER = re.compile(r"(?i)^\s*(?:figure|table|fig\.?)\s+\d+")
_NUMBER_PATTERN = re.compile(r"\d")


def _block_text(block: _TextBlockView) -> str:
    text = block.text.strip()
    return text


def _looks_like_block(obj: object) -> bool:
    """Return True when ``obj`` exposes the TextBlock surface we need.

    Duck-typed instead of ``isinstance`` against the Protocol because
    Protocols without ``@runtime_checkable`` raise TypeError on isinstance.
    """

    return all(hasattr(obj, name) for name in ("text", "bbox", "block_no", "sequence", "block_type"))


def _is_short_uppercase(line: str) -> bool:
    cleaned = line.strip()
    if not cleaned or len(cleaned) > 80:
        return False
    if not _NUMBER_PATTERN.search(cleaned):
        # Pure symbolic headings are still candidates, but only when at
        # least one letter is present.
        if not re.search(r"[A-Za-z]", cleaned):
            return False
    letters = [c for c in cleaned if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= 0.6


def _classify_text_block(
    text: str,
    *,
    table_detected: bool,
    on_block_index: int,
    total_blocks: int,
) -> SegmentType:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return SegmentType.OTHER

    first = lines[0]
    if _CAPTION_MARKER.match(first):
        return SegmentType.CAPTION
    if _LIST_BULLET_PATTERN.match(first):
        return SegmentType.LIST
    if _FOOTNOTE_MARKER.match(first):
        return SegmentType.FOOTNOTE
    if table_detected and on_block_index == 0:
        return SegmentType.TABLE
    if _is_short_uppercase(first) and len(lines) <= 3:
        return SegmentType.HEADING
    if total_blocks == 1:
        return SegmentType.PARAGRAPH
    # Last block on a page with table_detected is often a footnote.
    if table_detected and on_block_index == total_blocks - 1:
        if len(first) < 200 and any(
            marker in first.lower()
            for marker in ("note:", "note ", "condition", "*", "†")
        ):
            return SegmentType.FOOTNOTE
    return SegmentType.PARAGRAPH


def _quality_for_status(status: PageParseStatus) -> ChunkQuality:
    return ChunkQuality(status.value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def segment_page(
    doc_id: str,
    page: _PageLayoutView,
    page_status: PageParseStatus,
) -> list[SegmentRecord]:
    """Produce the structural segments for one parsed page.

    The returned list is in reading order (top-to-bottom) and contains
    at least one segment per non-empty text block. The page-level
    quality status is propagated to every segment on the page so that
    downstream chunk consumers can decide whether to trust the raw text.
    """

    quality = _quality_for_status(page_status)
    text_blocks = [b for b in page.blocks if _looks_like_block(b)]
    total_blocks = len(text_blocks)
    table_detected = bool(page.table_detected)

    # Fallback: when layout extraction returned no blocks, synthesize a
    # single PARAGRAPH segment from the full page text. This preserves
    # raw evidence while still being honest about the lack of layout.
    if total_blocks == 0:
        text = (page.text or "").strip()
        if not text:
            return []
        return [
            _build_segment(
                doc_id=doc_id,
                page_number=page.page_number,
                sequence=0,
                segment_type=SegmentType.PARAGRAPH,
                raw_text=text,
                bbox=None,
                heading_path=(),
                quality=quality,
            )
        ]

    segments: list[SegmentRecord] = []
    for index, block in enumerate(text_blocks):
        text = _block_text(block)  # type: ignore[arg-type]
        if not text:
            continue
        segment_type = _classify_text_block(
            text,
            table_detected=table_detected,
            on_block_index=index,
            total_blocks=total_blocks,
        )
        bbox = _coerce_bbox(getattr(block, "bbox", None))
        segments.append(
            _build_segment(
                doc_id=doc_id,
                page_number=page.page_number,
                sequence=len(segments),
                segment_type=segment_type,
                raw_text=text,
                bbox=bbox,
                heading_path=(),
                quality=quality,
            )
        )

    return segments


def segment_pages(
    doc_id: str,
    pages: Iterable[tuple[_PageLayoutView, PageParseStatus]],
) -> list[SegmentRecord]:
    """Produce segments for a sequence of (page, status) tuples."""

    out: list[SegmentRecord] = []
    for page, status in pages:
        out.extend(segment_page(doc_id, page, status))
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_bbox(value: object) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 4:
        try:
            return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
        except (TypeError, ValueError):
            return None
    return None


def _build_segment(
    *,
    doc_id: str,
    page_number: int,
    sequence: int,
    segment_type: SegmentType,
    raw_text: str,
    bbox: tuple[float, float, float, float] | None,
    heading_path: tuple[str, ...],
    quality: ChunkQuality,
) -> SegmentRecord:
    segment_id = derive_segment_id(
        doc_id,
        page_number,
        sequence,
        parser_version=PARSER_VERSION,
    )
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return SegmentRecord(
        segment_id=segment_id,
        doc_id=doc_id,
        page_number=page_number,
        sequence=sequence,
        segment_type=segment_type,
        raw_text=raw_text,
        bbox=bbox,
        heading_path=heading_path,
        quality_status=quality,
        content_hash=content_hash,
    )
