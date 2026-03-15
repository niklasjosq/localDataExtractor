from __future__ import annotations

from pathlib import Path
import subprocess

from localdataextractor.models import ParsedResult
from localdataextractor.parsers.base import ParserContext
from localdataextractor.parsers.common import plain_text_to_blocks


class TikaParser:
    name = "tika"

    def extract(self, path: Path, context: ParserContext) -> ParsedResult:
        warnings: list[str] = []
        jar = context.config.tika.tika_jar_path
        if not jar:
            return ParsedResult(
                parser_name=self.name,
                warnings=["Tika is not configured"],
            )

        cmd = ["java", "-jar", jar, "-t", str(path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        text = (proc.stdout or "").strip()
        if proc.returncode != 0:
            warnings.append((proc.stderr or "").strip() or "Tika command failed")

        blocks = plain_text_to_blocks(text)
        return ParsedResult(parser_name=self.name, blocks=blocks, warnings=warnings)
