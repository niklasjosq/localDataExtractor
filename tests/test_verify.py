from __future__ import annotations

from pathlib import Path

from localdataextractor.verify import verify_output_tree


def test_verify_output_tree(tmp_path: Path) -> None:
    out = tmp_path / "output"
    out.mkdir()
    base = out / "a"
    base.with_suffix(".md").write_text("# hello\n", encoding="utf-8")
    base.with_suffix(".log").write_text("ok\n", encoding="utf-8")
    base.with_suffix(".json").write_text(
        '{"schema_version":"1.0","source":{},"extraction_attempts":[],"route_history":[{"route_id":"x"}],"overall_confidence":99,"below_threshold":false,"tables":[]}',
        encoding="utf-8",
    )

    report = verify_output_tree(out)
    assert report.total == 1
    assert report.failed == 0
    assert report.ok == 1
