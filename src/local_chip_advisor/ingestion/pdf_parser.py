"""Deterministic local PDF parsing with stable page provenance.

The base parser returns a one-based page text snapshot for downstream
consumers. The layout parser extends that snapshot with image counts,
text-block coordinates, and a non-empty table presence flag for S05
page-quality diagnostics. Both APIs reuse one PyMuPDF open so the SHA-256
fingerprint and page provenance stay the single source of truth.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pymupdf


@dataclass(frozen=True)
class ParsedPage:
    """Text extracted from one physical PDF page."""

    page_number: int
    text: str


@dataclass(frozen=True)
class TextBlock:
    """One textual block on a page with its bbox.

    ``block_type`` follows PyMuPDF's block classification:
    0 = text, 1 = image. ``block_no`` and ``sequence`` preserve the raw
    document order so callers can recreate the original layout.
    """

    block_no: int
    sequence: int
    block_type: int
    bbox: tuple[float, float, float, float]
    text: str
    line_count: int


@dataclass(frozen=True)
class ParsedPdf:
    """Parsed local PDF together with its immutable file fingerprint."""

    path: Path
    sha256: str
    page_count: int
    pages: tuple[ParsedPage, ...]


@dataclass(frozen=True)
class ParsedPageLayout:
    """One page with layout diagnostics for S05 quality classification."""

    page_number: int
    text: str
    char_count: int
    image_count: int
    block_count: int
    text_block_count: int
    image_block_count: int
    table_detected: bool
    blocks: tuple[TextBlock, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ParsedPdfLayout:
    """Parsed local PDF with per-page layout diagnostics."""

    path: Path
    sha256: str
    page_count: int
    pages: tuple[ParsedPageLayout, ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _open_pdf(path: Path) -> pymupdf.Document:
    if not path.exists():
        raise FileNotFoundError(path)

    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise ValueError(f"file is not a valid PDF: {path}") from exc

    if not document.is_pdf:
        document.close()
        raise ValueError(f"file is not a valid PDF: {path}")

    return document


def parse_pdf(path: str | Path) -> ParsedPdf:
    """Parse a local PDF while preserving physical 1-based page numbers."""

    pdf_path = Path(path)
    document = _open_pdf(pdf_path)

    try:
        sha256 = _sha256_file(pdf_path)

        pages = tuple(
            ParsedPage(
                page_number=index + 1,
                text=page.get_text("text"),
            )
            for index, page in enumerate(document)
        )

        return ParsedPdf(
            path=pdf_path,
            sha256=sha256,
            page_count=document.page_count,
            pages=pages,
        )
    finally:
        document.close()


def _text_blocks(page: pymupdf.Page) -> tuple[TextBlock, ...]:
    raw_blocks: Iterable[tuple[float, ...]] = page.get_text("blocks")
    blocks: list[TextBlock] = []

    for block_no, block in enumerate(raw_blocks):
        # PyMuPDF block tuple: (x0, y0, x1, y1, text, block_no, block_type).
        # Older or newer bindings can reorder; locate text by type.
        if len(block) < 7:
            continue

        x0, y0, x1, y1 = block[0], block[1], block[2], block[3]
        text = block[4] if isinstance(block[4], str) else ""
        block_type = int(block[6])

        if block_type != 0:
            continue

        if not text.strip():
            continue

        line_marker = "\n"
        line_count = text.count(line_marker) + (1 if text.strip() else 0)

        blocks.append(
            TextBlock(
                block_no=block_no,
                sequence=len(blocks),
                block_type=block_type,
                bbox=(float(x0), float(y0), float(x1), float(y1)),
                text=text,
                line_count=line_count,
            )
        )

    return tuple(blocks)


def _image_count(page: pymupdf.Page) -> int:
    # ``get_images(full=True)`` in PyMuDF 1.28 returns the cumulative
    # document-wide image list (a known quirk), so it cannot be used
    # for per-page counting. ``get_image_info`` returns one entry per
    # image XObject actually placed on the current page, which is what
    # the S05 page-quality classifier needs.
    return len(page.get_image_info())


def _table_detected(page: pymupdf.Page) -> bool:
    finder = page.find_tables()
    tables = finder.tables
    return bool(tables)


def parse_pdf_layout(path: str | Path) -> ParsedPdfLayout:
    """Parse a local PDF with per-page layout diagnostics.

    Equivalent to :func:`parse_pdf` for text and provenance, plus block
    coordinates, image counts, and a non-empty table presence flag.
    """

    pdf_path = Path(path)
    document = _open_pdf(pdf_path)

    try:
        sha256 = _sha256_file(pdf_path)

        pages: list[ParsedPageLayout] = []

        for index, page in enumerate(document):
            text = page.get_text("text")
            blocks = _text_blocks(page)
            image_count = _image_count(page)
            table_detected = _table_detected(page)
            image_block_count = sum(
                1
                for raw_block in page.get_text("blocks")
                if len(raw_block) >= 7 and int(raw_block[6]) == 1
            )

            pages.append(
                ParsedPageLayout(
                    page_number=index + 1,
                    text=text,
                    char_count=len(text),
                    image_count=image_count,
                    block_count=len(blocks) + image_block_count,
                    text_block_count=len(blocks),
                    image_block_count=image_block_count,
                    table_detected=table_detected,
                    blocks=blocks,
                )
            )

        return ParsedPdfLayout(
            path=pdf_path,
            sha256=sha256,
            page_count=document.page_count,
            pages=tuple(pages),
        )
    finally:
        document.close()