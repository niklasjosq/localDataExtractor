from __future__ import annotations

from localdataextractor.config import load_config
from localdataextractor.models import ContentBlock, ParsedResult, TableBlock
from localdataextractor.quality.scoring import needs_retry, score_extraction


def test_table_validation_lowers_score() -> None:
    config = load_config(None)
    parsed = ParsedResult(
        parser_name="test",
        blocks=[ContentBlock(block_id="1", block_type="paragraph", text="hello", confidence=90.0)],
        tables=[
            TableBlock(
                table_id="tbl_1",
                header_rows=[["A", "B"]],
                body_rows=[["1"], ["2", "2"]],
                column_count=2,
                row_count=2,
                confidence=90.0,
            )
        ],
    )
    scoring = score_extraction(parsed, config, "pdf")
    assert scoring.report.overall < 100
    assert scoring.report.table_scores["tbl_1"] < 95


def test_retry_triggers_for_low_table_confidence() -> None:
    config = load_config(None)
    report = type("Rep", (), {"overall": 99.0})()
    table = TableBlock(
        table_id="tbl_1",
        header_rows=[["A", "B"]],
        body_rows=[["x", "y"]],
        column_count=2,
        row_count=1,
        confidence=80.0,
    )
    needed, reasons = needs_retry(report, ".pdf", config, [table])
    assert needed
    assert any("important_table_below_threshold" in reason for reason in reasons)
