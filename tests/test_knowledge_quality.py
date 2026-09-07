"""Contract tests for the deterministic page-quality classifier."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from local_chip_advisor.knowledge import (
    LOW_TEXT_CHAR_THRESHOLD,
    PageParseStatus,
    classify_page,
)


@dataclass(frozen=True)
class _FakePage:
    page_number: int
    text: str
    char_count: int
    image_count: int
    text_block_count: int
    image_block_count: int
    table_detected: bool


def _page(
    text: str = "Hello datasheet",
    *,
    image_count: int = 0,
    text_block_count: int = 1,
    image_block_count: int = 0,
    table_detected: bool = False,
) -> _FakePage:
    return _FakePage(
        page_number=1,
        text=text,
        char_count=len(text),
        image_count=image_count,
        text_block_count=text_block_count,
        image_block_count=image_block_count,
        table_detected=table_detected,
    )


def test_classify_page_marks_low_text_below_threshold() -> None:
    body = "a" * (LOW_TEXT_CHAR_THRESHOLD - 1)

    status, hint = classify_page(_page(body))

    assert status is PageParseStatus.LOW_TEXT
    # Hint is a navigation aid and is truncated to 80 chars.
    assert hint == "a" * 80


def test_classify_page_marks_ok_when_text_is_substantial() -> None:
    body = "MP4570 recommended operating conditions " * 30

    status, hint = classify_page(_page(body))

    assert status is PageParseStatus.OK
    assert hint is not None
    assert hint.startswith("MP4570")


def test_classify_page_marks_image_heavy_when_images_dominate() -> None:
    # A small caption is present so the page is not NEEDS_OCR; the bulk
    # of the page area is images, so it should be IMAGE_HEAVY.
    status, _ = classify_page(
        _page(
            text="Figure 3 Efficiency vs Load",
            image_count=3,
            text_block_count=1,
            image_block_count=4,
        )
    )

    assert status is PageParseStatus.IMAGE_HEAVY


def test_classify_page_marks_needs_ocr_when_only_images_present() -> None:
    status, _ = classify_page(
        _page(text="", image_count=1, text_block_count=0, image_block_count=1)
    )

    assert status is PageParseStatus.NEEDS_OCR


def test_classify_page_marks_parse_error_when_completely_empty() -> None:
    status, hint = classify_page(
        _page(text="", text_block_count=0, image_count=0)
    )

    assert status is PageParseStatus.PARSE_ERROR
    assert hint is None


def test_classify_page_marks_table_uncertain_when_layout_thin() -> None:
    body = ("PARAMETER CONDITIONS MIN TYP MAX UNIT VIN VOUT V " * 8).strip()

    status, _ = classify_page(
        _page(
            text=body,
            text_block_count=1,
            table_detected=True,
        )
    )

    assert status is PageParseStatus.TABLE_UNCERTAIN


def test_classify_page_is_deterministic() -> None:
    page = _page("MP4570 efficiency curve figure follows")

    first = classify_page(page)
    second = classify_page(page)

    assert first == second
