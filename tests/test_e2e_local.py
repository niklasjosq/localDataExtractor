from __future__ import annotations

from pathlib import Path
import json

from localdataextractor.config import load_config
from localdataextractor.pipeline import IngestionPipeline
from localdataextractor.verify import verify_output_tree


def test_e2e_txt_css_ingest(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    (input_dir / "note.txt").write_text("Line one\n\nLine two", encoding="utf-8")
    (input_dir / "styles.css").write_text("body { color: black; }", encoding="utf-8")

    config = load_config(None)
    config.llm.enable_vlm_repair = False
    pipeline = IngestionPipeline(config)

    state_file = pipeline.ingest(input_dir, output_dir, max_workers=1, explain_route=True)
    assert state_file.exists()

    note_json = output_dir / "note.json"
    css_md = output_dir / "styles.md"
    assert note_json.exists()
    assert css_md.exists()

    note_payload = json.loads(note_json.read_text(encoding="utf-8"))
    assert "overall_confidence" in note_payload
    assert "route_history" in note_payload

    css_md_text = css_md.read_text(encoding="utf-8")
    assert "```css" in css_md_text

    report = verify_output_tree(output_dir)
    assert report.total >= 2
