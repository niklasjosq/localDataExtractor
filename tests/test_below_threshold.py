from __future__ import annotations

from pathlib import Path
import json

from localdataextractor.config import load_config
from localdataextractor.models import ContentBlock, ParsedResult
from localdataextractor.pipeline import IngestionPipeline


class AlwaysLowParserManager:
    def extract(self, parser_name: str, path: Path, context):  # noqa: ANN001
        return ParsedResult(
            parser_name=parser_name,
            blocks=[ContentBlock(block_id="1", block_type="paragraph", text="x", confidence=40.0)],
            tables=[],
            warnings=["forced low confidence"],
        )


def test_below_threshold_flagged_when_all_routes_fail(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    (input_dir / "a.pdf").write_text("dummy", encoding="utf-8")

    config = load_config(None)
    config.llm.enable_vlm_repair = False
    pipeline = IngestionPipeline(config)
    pipeline.parser_manager = AlwaysLowParserManager()

    state_file = pipeline.ingest(input_dir, output_dir, max_workers=1)
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    state = payload["files"]["a.pdf"]
    assert state["status"] == "completed_below_threshold"

    out_json = output_dir / "a.json"
    doc_payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc_payload["below_threshold"] is True
