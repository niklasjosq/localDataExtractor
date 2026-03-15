from __future__ import annotations

from pathlib import Path

from localdataextractor.models import ContentBlock, ParsedResult
from localdataextractor.parsers.base import ParserContext
from localdataextractor.parsers.common import plain_text_to_blocks


class TextParser:
    name = "text"

    def extract(self, path: Path, context: ParserContext) -> ParsedResult:
        data = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".css":
            fenced = f"```css\n{data.strip()}\n```\n"
            blocks = [
                ContentBlock(
                    block_id="blk_00001",
                    block_type="code",
                    text=fenced,
                    confidence=99.0,
                )
            ]
            return ParsedResult(parser_name=self.name, blocks=blocks)

        blocks = plain_text_to_blocks(data)
        return ParsedResult(parser_name=self.name, blocks=blocks)
