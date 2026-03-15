from __future__ import annotations

from pathlib import Path
import tempfile

from localdataextractor.models import ParsedResult
from localdataextractor.parsers.base import ParserContext
from localdataextractor.parsers.docling_parser import DoclingParser
from localdataextractor.parsers.libreoffice_converter import convert_with_libreoffice
from localdataextractor.parsers.markitdown_parser import MarkItDownParser
from localdataextractor.parsers.ocr_docling_parser import OCRDoclingParser
from localdataextractor.parsers.text_parser import TextParser
from localdataextractor.parsers.tika_parser import TikaParser


class ParserManager:
    def __init__(self) -> None:
        self.text = TextParser()
        self.markitdown = MarkItDownParser()
        self.docling = DoclingParser()
        self.ocr_docling = OCRDoclingParser()
        self.tika = TikaParser()

    def extract(self, parser_name: str, path: Path, context: ParserContext) -> ParsedResult:
        if parser_name == "text":
            return self.text.extract(path, context)
        if parser_name == "markitdown":
            return self.markitdown.extract(path, context)
        if parser_name == "docling":
            return self.docling.extract(path, context)
        if parser_name == "ocr_docling":
            return self.ocr_docling.extract(path, context)
        if parser_name == "tika":
            return self.tika.extract(path, context)
        if parser_name == "libreoffice_markitdown":
            return self._extract_with_libreoffice(path, context, self.markitdown)
        if parser_name == "libreoffice_docling":
            return self._extract_with_libreoffice(path, context, self.docling)
        return ParsedResult(parser_name=parser_name, warnings=[f"Unknown parser: {parser_name}"])

    def _extract_with_libreoffice(
        self,
        path: Path,
        context: ParserContext,
        parser: MarkItDownParser | DoclingParser,
    ) -> ParsedResult:
        with tempfile.TemporaryDirectory(prefix="localdataextractor-lo-") as tmp:
            converted, message = convert_with_libreoffice(path, Path(tmp))
            if not converted:
                return ParsedResult(
                    parser_name=f"{parser.name}_libreoffice",
                    warnings=[f"LibreOffice conversion failed: {message}"],
                )

            result = parser.extract(converted, context)
            result.warnings.append("LibreOffice conversion applied")
            result.artifacts["converted_file"] = str(converted)
            return result
