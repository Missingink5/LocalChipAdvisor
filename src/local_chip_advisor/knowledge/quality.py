"""Deterministic page-quality classifier for S05 ingestion.

S05 must classify each page's extraction quality without any LLM or
embedding call. The classifier consumes the layout diagnostics already
returned by :func:`local_chip_advisor.ingestion.parse_pdf_layout` and
assigns a :class:`PageParseStatus` plus an optional section hint.

The rules below are intentionally simple and explainable. They are not
truth claims about the page content; they describe how confidently the
downstream chunker can rely on ``raw_text`` as a faithful representation
of the PDF page.
"""

from __future__ import annotations

from typing import Protocol

from .models import PageParseStatus


class _PageLayoutView(Protocol):
    """Structural subset of :class:`ParsedPageLayout` consumed here.

    Defined as a Protocol so :mod:`knowledge.quality` does not need to
    import :class:`ParsedPageLayout` from :mod:`ingestion`. Keeping the
    dependency one-way (knowledge → ingestion only via this Protocol)
    preserves the S05 layering rule.
    """

    page_number: int
    text: str
    char_count: int
    image_count: int
    text_block_count: int
    image_block_count: int
    table_detected: bool


# Lower bound for "page has enough text to trust" on a vendor datasheet.
# Picked empirically from MP4570 body pages versus the title/cover/empty
# pages. Pages strictly below this threshold are tagged ``LOW_TEXT`` so
# downstream consumers know to inspect ``raw_text`` before relying on it.
LOW_TEXT_CHAR_THRESHOLD = 200

# Image-heavy threshold. A page whose text-block coverage is dwarfed by
# images (typical efficiency-curve pages) is marked IMAGE_HEAVY. The
# classifier does NOT attempt OCR or numeric extraction; downstream
# consumers must treat such chunks as locator-only.
IMAGE_HEAVY_BLOCK_RATIO = 0.5


def classify_page(page: _PageLayoutView) -> tuple[PageParseStatus, str | None]:
    """Return ``(parse_status, section_hint)`` for one parsed page.

    The classifier is pure and deterministic: identical layout input
    always produces identical output. It does not mutate ``page`` and
    has no I/O side effects.
    """

    text = page.text
    char_count = page.char_count
    image_count = page.image_count
    text_block_count = page.text_block_count
    image_block_count = page.image_block_count
    table_detected = page.table_detected

    # 1. Parse error: no text, no images, no text blocks. The PDF
    #    surface for this page is structurally empty.
    if char_count == 0 and image_count == 0 and text_block_count == 0:
        return PageParseStatus.PARSE_ERROR, None

    # 2. Needs OCR: text layer effectively empty but image layer present.
    #    S05 does NOT run OCR; this is a documented gap. We distinguish
    #    this case from IMAGE_HEAVY because a NEEDS_OCR page has no text
    #    at all, while an IMAGE_HEAVY page may have a few captions.
    if image_count >= 1 and char_count == 0:
        return PageParseStatus.NEEDS_OCR, None

    # 3. Table uncertain: a table was detected but the layout parser
    #    surfaced too few text blocks to confidently reconstruct rows.
    if table_detected and text_block_count <= 2:
        return PageParseStatus.TABLE_UNCERTAIN, _section_hint_for_text(text)

    # 4. Image heavy: many images, very little text → curve/diagram page.
    # We compare ``image_count`` (from page.get_images) against the
    # number of textual layout blocks. The parser does not surface
    # image-as-block entries from get_text("blocks"), so the more
    # reliable signal is the count of images directly.
    if (
        image_count >= 1
        and char_count < LOW_TEXT_CHAR_THRESHOLD
        and (text_block_count == 0 or image_count >= text_block_count)
    ):
        return PageParseStatus.IMAGE_HEAVY, _section_hint_for_image_page(text)

    # 5. Low text: barely any extractable text on an otherwise normal page.
    if char_count < LOW_TEXT_CHAR_THRESHOLD:
        return PageParseStatus.LOW_TEXT, _section_hint_for_text(text)

    # 6. OK: default for normal text-heavy pages.
    return PageParseStatus.OK, _section_hint_for_text(text)


def _section_hint_for_text(text: str) -> str | None:
    """Return a short section hint from the first non-empty line, if any.

    The hint is purely a navigation aid. It is NOT a section heading
    claim and is never used as a chunk provenance anchor by itself.
    """

    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:80]
    return None


def _section_hint_for_image_page(text: str) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    return cleaned[:80]
