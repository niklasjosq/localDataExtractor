from __future__ import annotations

from pathlib import Path
import json

from localdataextractor.config import load_config
from localdataextractor.pipeline import IngestionPipeline


def test_resume_processes_pending_files(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    (input_dir / "a.txt").write_text("hello world " * 20, encoding="utf-8")
    (input_dir / "b.txt").write_text("another doc " * 20, encoding="utf-8")

    config = load_config(None)
    config.llm.enable_vlm_repair = False
    pipeline = IngestionPipeline(config)

    state_file = pipeline.ingest(input_dir, output_dir, max_workers=1)
    payload = json.loads(state_file.read_text(encoding="utf-8"))

    payload["files"]["b.txt"]["status"] = "pending"
    state_file.write_text(json.dumps(payload), encoding="utf-8")

    pipeline.resume(state_file, max_workers=1)
    payload2 = json.loads(state_file.read_text(encoding="utf-8"))

    assert payload2["files"]["b.txt"]["status"] != "pending"
