from __future__ import annotations

from pathlib import Path
import fnmatch
import os
import re
from typing import Iterable

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".css",
    ".xls",
    ".xlsx",
    ".txt",
    ".ppt",
    ".pptx",
}


def sanitize_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "unnamed"


def safe_relpath(path: Path, root: Path) -> Path:
    rel = path.resolve().relative_to(root.resolve())
    return Path(*[sanitize_segment(part) for part in rel.parts])


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_input_files(
    input_path: Path,
    include_globs: Iterable[str],
    exclude_globs: Iterable[str],
) -> list[Path]:
    files: list[Path] = []
    if input_path.is_file():
        files = [input_path]
    else:
        files = [p for p in input_path.rglob("*") if p.is_file()]

    selected: list[Path] = []
    for file in files:
        rel = str(file.relative_to(input_path if input_path.is_dir() else file.parent))
        included = any(fnmatch.fnmatch(rel, pattern) for pattern in include_globs)
        excluded = any(fnmatch.fnmatch(rel, pattern) for pattern in exclude_globs)
        if included and not excluded and file.suffix.lower() in SUPPORTED_EXTENSIONS:
            selected.append(file)
    return sorted(selected)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(content)
    os.replace(temp, path)
