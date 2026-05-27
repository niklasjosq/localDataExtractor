from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
import logging

from localdataextractor.config import AppConfig
from localdataextractor.models import ParsedResult


@dataclass(slots=True)
class ParserContext:
    config: AppConfig
    temp_dir: Path
    logger: logging.Logger
    route_id: str
    debug_dir: Path | None = None
    extra: dict[str, str] = field(default_factory=dict)
    discard_garbled: bool = True


class Parser(Protocol):
    name: str

    def extract(self, path: Path, context: ParserContext) -> ParsedResult:
        ...
