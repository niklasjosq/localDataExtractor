from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from localdataextractor.utils.filesystem import atomic_write_text


def write_json(path: Path, payload: Any) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    atomic_write_text(path, content + "\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
