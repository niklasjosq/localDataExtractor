from __future__ import annotations

from localdataextractor.config import load_config
from localdataextractor.models import ContentBlock, ParsedResult
from localdataextractor.quality.scoring import score_extraction
from localdataextractor.utils.text_quality import (
    looks_garbled,
    replacement_ratio,
)


def test_replacement_ratio_clean_text() -> None:
    assert replacement_ratio("hello world") == 0.0
    assert not looks_garbled("hello world")


def test_replacement_ratio_with_replacement_char() -> None:
    text = "abc" + ("�" * 20)
    assert replacement_ratio(text) > 0.5
    assert looks_garbled(text)


def test_private_use_area_counts_as_garbled() -> None:
    text = "abc" + ("" * 20)
    assert looks_garbled(text)


def test_clean_text_not_flagged_below_threshold() -> None:
    text = "Lorem ipsum dolor sit amet" + "�"
    assert not looks_garbled(text)


def test_result_is_garbled_detects_via_warning_only() -> None:
    from localdataextractor.parsers.ocr_docling_parser import (
        _result_is_garbled,
    )

    empty_with_warning = ParsedResult(
        parser_name="docling",
        blocks=[],
        warnings=["garbled_text_layer: replacement_ratio=0.42"],
    )
    assert _result_is_garbled(empty_with_warning) is True

    empty_with_hint = ParsedResult(
        parser_name="docling",
        blocks=[],
        scanned_hint=True,
    )
    assert _result_is_garbled(empty_with_hint) is True

    clean = ParsedResult(
        parser_name="docling",
        blocks=[
            ContentBlock(
                block_id="b1",
                block_type="paragraph",
                text="Lorem ipsum dolor sit amet",
            ),
        ],
    )
    assert _result_is_garbled(clean) is False


def test_scoring_penalty_for_garbled_block() -> None:
    config = load_config(None)
    garbled_text = "abc" + ("�" * 200)
    parsed = ParsedResult(
        parser_name="test",
        blocks=[
            ContentBlock(
                block_id="b1",
                block_type="paragraph",
                text=garbled_text,
                confidence=95.0,
            ),
        ],
    )
    scoring = score_extraction(parsed, config, "pdf")
    assert scoring.report.overall < 50
    assert any(
        "garbled_text_layer" in w for w in parsed.warnings
    )
