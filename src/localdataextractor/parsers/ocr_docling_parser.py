from __future__ import annotations

from pathlib import Path
import tempfile

from localdataextractor.models import ParsedResult
from localdataextractor.ocr.ocrmypdf_runner import run_ocrmypdf
from localdataextractor.parsers.base import ParserContext
from localdataextractor.parsers.docling_parser import DoclingParser


class OCRDoclingParser:
    name = "ocr_docling"

    def __init__(self) -> None:
        self._docling = DoclingParser()

    def extract(self, path: Path, context: ParserContext) -> ParsedResult:
        if path.suffix.lower() != ".pdf":
            result = self._docling.extract(path, context)
            result.warnings.append("ocr_docling route used on non-PDF input")
            return result

        with tempfile.TemporaryDirectory(prefix="localdataextractor-ocr-") as tmp:
            ocr_pdf = Path(tmp) / f"{path.stem}.ocr.pdf"
            ok, message = run_ocrmypdf(path, ocr_pdf, context.config.ocr)
            if not ok:
                result = self._docling.extract(path, context)
                result.warnings.append(f"OCRmyPDF failed, fallback to direct parse: {message}")
                return result

            result = self._docling.extract(ocr_pdf, context)
            result.warnings.append("OCRmyPDF pre-processing applied")
            result.artifacts["ocr_pdf"] = str(ocr_pdf)
            return result
