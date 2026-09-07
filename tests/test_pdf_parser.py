"""Contract tests for local PDF parsing with stable page provenance."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

from local_chip_advisor.ingestion.pdf_parser import (
    ParsedPageLayout,
    parse_pdf,
    parse_pdf_layout,
)


def create_test_pdf(path: Path) -> None:
    document = pymupdf.open()

    page1 = document.new_page()
    page1.insert_text(
        (72, 72),
        "MP4570 TEST PAGE ONE\nRecommended input range: 4.5V to 55V",
    )

    page2 = document.new_page()
    page2.insert_text(
        (72, 72),
        "MP4570 TEST PAGE TWO\nContinuous output current: 3A",
    )

    document.save(path)
    document.close()


def create_image_heavy_pdf(path: Path) -> None:
    """Produce a page whose text is empty but whose image list is non-empty."""

    document = pymupdf.open()
    page = document.new_page(width=400, height=400)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), 0)
    pix.clear_with(255)
    image_bytes = pix.tobytes("png")
    page.insert_image(pymupdf.Rect(50, 50, 250, 250), stream=image_bytes)
    document.save(path)
    document.close()


def test_parse_pdf_preserves_one_based_page_numbers(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    create_test_pdf(pdf_path)

    parsed = parse_pdf(pdf_path)

    assert parsed.page_count == 2
    assert tuple(page.page_number for page in parsed.pages) == (1, 2)


def test_parse_pdf_extracts_text_per_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    create_test_pdf(pdf_path)

    parsed = parse_pdf(pdf_path)

    assert "4.5V to 55V" in parsed.pages[0].text
    assert "3A" in parsed.pages[1].text


def test_parse_pdf_records_actual_sha256(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    create_test_pdf(pdf_path)

    expected_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    parsed = parse_pdf(pdf_path)

    assert parsed.sha256 == expected_sha256
    assert len(parsed.sha256) == 64


def test_parse_pdf_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError):
        parse_pdf(missing)


def test_parse_pdf_rejects_non_pdf_file(tmp_path: Path) -> None:
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("this is not a real PDF", encoding="utf-8")

    with pytest.raises(ValueError, match="valid PDF"):
        parse_pdf(fake_pdf)


def test_parse_pdf_layout_matches_parse_pdf_text_and_sha(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    create_test_pdf(pdf_path)

    base = parse_pdf(pdf_path)
    layout = parse_pdf_layout(pdf_path)

    assert layout.sha256 == base.sha256
    assert layout.page_count == base.page_count
    assert tuple(p.page_number for p in layout.pages) == tuple(
        p.page_number for p in base.pages
    )
    for layout_page, base_page in zip(layout.pages, base.pages):
        assert layout_page.text == base_page.text
        assert isinstance(layout_page, ParsedPageLayout)


def test_parse_pdf_layout_counts_images_on_image_heavy_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "image_heavy.pdf"
    create_image_heavy_pdf(pdf_path)

    layout = parse_pdf_layout(pdf_path)

    page_one = layout.pages[0]
    assert page_one.image_count >= 1
    assert page_one.text_block_count == 0
    assert page_one.char_count == 0