"""Deterministic local PDF parsing with stable page provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class ParsedPage:
    """Text extracted from one physical PDF page."""

    page_number: int
    text: str


@dataclass(frozen=True)
class ParsedPdf:
    """Parsed local PDF together with its immutable file fingerprint."""

    path: Path
    sha256: str
    page_count: int
    pages: tuple[ParsedPage, ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def parse_pdf(path: str | Path) -> ParsedPdf:
    """Parse a local PDF while preserving physical 1-based page numbers."""

    pdf_path = Path(path)

    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    if not pdf_path.is_file():
        raise ValueError(f"path is not a file: {pdf_path}")

    sha256 = _sha256_file(pdf_path)

    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:
        raise ValueError(f"file is not a valid PDF: {pdf_path}") from exc

    try:
        if not document.is_pdf:
            raise ValueError(f"file is not a valid PDF: {pdf_path}")

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
