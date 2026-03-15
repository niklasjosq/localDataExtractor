from __future__ import annotations

from pathlib import Path

from localdataextractor.config import load_config
from localdataextractor.models import ContentBlock, ParsedResult, TableBlock
from localdataextractor.pipeline import IngestionPipeline


class FakeParserManager:
    def __init__(self) -> None:
        self.count = 0

    def extract(self, parser_name: str, path: Path, context):  # noqa: ANN001
        self.count += 1
        if self.count == 1:
            return ParsedResult(
                parser_name=parser_name,
                blocks=[ContentBlock(block_id="1", block_type="paragraph", text="tiny", confidence=70.0)],
                tables=[
                    TableBlock(
                        table_id="tbl_low",
                        header_rows=[["A", "B"]],
                        body_rows=[["1"], ["2"]],
                        column_count=2,
                        row_count=2,
                        confidence=70.0,
                    )
                ],
            )
        return ParsedResult(
            parser_name=parser_name,
            blocks=[
                ContentBlock(
                    block_id="1",
                    block_type="paragraph",
                    text="This is a much longer successful extraction." * 20,
                    confidence=99.0,
                )
            ],
            tables=[
                TableBlock(
                    table_id="tbl_ok",
                    header_rows=[["A", "B"]],
                    body_rows=[["1", "2"], ["3", "4"]],
                    column_count=2,
                    row_count=2,
                    confidence=99.0,
                )
            ],
        )


def test_retry_uses_next_route(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    pdf_file = input_dir / "sample.pdf"
    pdf_file.write_text("not-a-real-pdf", encoding="utf-8")

    config = load_config(None)
    config.llm.enable_vlm_repair = False
    pipeline = IngestionPipeline(config)
    pipeline.parser_manager = FakeParserManager()

    state_file = pipeline.ingest(input_dir, output_dir, max_workers=1)
    assert state_file.exists()

    import json

    state = json.loads(state_file.read_text(encoding="utf-8"))
    file_state = state["files"]["sample.pdf"]
    assert file_state["retries"] >= 1
    assert file_state["status"] in {"completed", "completed_below_threshold"}
