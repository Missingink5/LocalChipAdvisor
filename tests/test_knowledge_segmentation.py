"""Contract tests for the deterministic structural segmenter."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from local_chip_advisor.knowledge import (
    PARSER_VERSION,
    PageParseStatus,
    SegmentType,
    derive_segment_id,
)
from local_chip_advisor.knowledge.segmentation import segment_page


@dataclass(frozen=True)
class _FakeBlock:
    block_no: int
    sequence: int
    block_type: int
    bbox: tuple[float, float, float, float]
    text: str
    line_count: int


@dataclass(frozen=True)
class _FakePage:
    page_number: int
    text: str
    char_count: int
    image_count: int
    text_block_count: int
    image_block_count: int
    table_detected: bool
    blocks: tuple[_FakeBlock, ...]


def _page(
    text: str,
    blocks: tuple[_FakeBlock, ...],
    *,
    table_detected: bool = False,
) -> _FakePage:
    return _FakePage(
        page_number=1,
        text=text,
        char_count=len(text),
        image_count=0,
        text_block_count=len(blocks),
        image_block_count=0,
        table_detected=table_detected,
        blocks=blocks,
    )


def test_segment_page_returns_empty_list_when_page_is_blank() -> None:
    page = _page("", blocks=(), table_detected=False)

    segments = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)

    assert segments == []


def test_segment_page_classifies_uppercase_short_block_as_heading() -> None:
    blocks = (
        _FakeBlock(0, 0, 0, (10.0, 10.0, 200.0, 30.0), "ABSOLUTE MAXIMUM RATINGS", 1),
    )
    page = _page("ABSOLUTE MAXIMUM RATINGS", blocks)

    segments = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)

    assert len(segments) == 1
    assert segments[0].segment_type is SegmentType.HEADING


def test_segment_page_classifies_bullet_lines_as_list() -> None:
    blocks = (
        _FakeBlock(
            0,
            0,
            0,
            (10.0, 10.0, 200.0, 100.0),
            "- Input range: 4.5V to 55V\n- Output current: 3A",
            2,
        ),
    )
    page = _page("- Input range: 4.5V to 55V", blocks)

    segments = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)

    assert segments[0].segment_type is SegmentType.LIST


def test_segment_page_classifies_figure_caption() -> None:
    blocks = (
        _FakeBlock(
            0,
            0,
            0,
            (10.0, 200.0, 400.0, 220.0),
            "Figure 1. Functional block diagram",
            1,
        ),
    )
    page = _page("Figure 1. Functional block diagram", blocks)

    segments = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)

    assert segments[0].segment_type is SegmentType.CAPTION


def test_segment_page_classifies_long_body_as_paragraph() -> None:
    body = (
        "The MP4570 is a high-efficiency synchronous step-down converter. "
        "It operates over a wide input range and delivers up to 3A of "
        "continuous output current. The device integrates low RDSon power "
        "MOSFETs to minimize conduction losses."
    )
    blocks = (_FakeBlock(0, 0, 0, (10.0, 10.0, 400.0, 200.0), body, 4),)
    page = _page(body, blocks)

    segments = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)

    assert segments[0].segment_type is SegmentType.PARAGRAPH


def test_segment_page_propagates_page_quality_to_segments() -> None:
    blocks = (
        _FakeBlock(
            0,
            0,
            0,
            (10.0, 10.0, 200.0, 100.0),
            "Efficiency curve measured under nominal conditions.",
            1,
        ),
    )
    page = _page("", blocks)

    segments = segment_page(
        "doc:test:abcdabcdabcd", page, PageParseStatus.IMAGE_HEAVY
    )

    assert segments[0].quality_status.value == PageParseStatus.IMAGE_HEAVY.value


def test_segment_page_assigns_deterministic_segment_ids() -> None:
    blocks = (_FakeBlock(0, 0, 0, (10.0, 10.0, 200.0, 100.0), "Body paragraph text.", 1),)
    page = _page("Body paragraph text.", blocks)

    first = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)
    second = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)

    assert [s.segment_id for s in first] == [s.segment_id for s in second]
    expected = derive_segment_id(
        "doc:test:abcdabcdabcd", 1, 0, parser_version=PARSER_VERSION
    )
    assert first[0].segment_id == expected


def test_segment_page_records_bbox_when_block_has_one() -> None:
    blocks = (
        _FakeBlock(
            0,
            0,
            0,
            (10.0, 20.0, 100.0, 200.0),
            "Body paragraph inside the bounding box.",
            1,
        ),
    )
    page = _page("Body paragraph inside the bounding box.", blocks)

    segments = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)

    assert segments[0].bbox == (10.0, 20.0, 100.0, 200.0)


def test_segment_page_falls_back_to_single_paragraph_when_no_blocks() -> None:
    body = "Standalone body text with no extractable layout blocks."
    page = _page(body, blocks=())

    segments = segment_page("doc:test:abcdabcdabcd", page, PageParseStatus.OK)

    assert len(segments) == 1
    assert segments[0].segment_type is SegmentType.PARAGRAPH
    assert segments[0].raw_text == body
