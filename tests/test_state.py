from __future__ import annotations

from pathlib import Path

from localdataextractor.state.store import JobStateStore


def test_state_roundtrip(tmp_path: Path) -> None:
    input_root = tmp_path / "in"
    output_root = tmp_path / "out"
    input_root.mkdir()
    output_root.mkdir()

    file_path = input_root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")

    store = JobStateStore(tmp_path / "job_state.json")
    created = store.create(input_root, output_root, [file_path])

    loaded = store.load()
    assert loaded.job_id == created.job_id
    assert len(loaded.files) == 1
    rel = "doc.txt"
    assert rel in loaded.files
