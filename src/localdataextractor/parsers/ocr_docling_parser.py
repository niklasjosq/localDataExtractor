from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile

from localdataextractor.models import ParsedResult
from localdataextractor.ocr.ocrmypdf_runner import run_ocrmypdf
from localdataextractor.parsers.base import ParserContext
from localdataextractor.parsers.docling_parser import DoclingParser
from localdataextractor.utils.text_quality import (
    looks_garbled,
    replacement_ratio,
)


class OCRDoclingParser:
    name = "ocr_docling"

    def __init__(self) -> None:
        self._docling = DoclingParser()

    def extract(self, path: Path, context: ParserContext) -> ParsedResult:
        if path.suffix.lower() != ".pdf":
            result = self._docling.extract(path, context)
            result.notes.append("ocr_docling route used on non-PDF input")
            return result

        ocr_cfg = context.config.ocr
        log = context.logger

        with tempfile.TemporaryDirectory(prefix="localdataextractor-ocr-") as tmp:
            ocr_pdf = Path(tmp) / f"{path.stem}.ocr.pdf"
            log.info("ocr_docling: running OCRmyPDF --skip-text on %s", path)
            ok, message = run_ocrmypdf(path, ocr_pdf, ocr_cfg)
            log.info(
                "ocr_docling: --skip-text exit=%s, output_exists=%s",
                ok, ocr_pdf.exists(),
            )
            if not ok:
                log.warning(
                    "ocr_docling: --skip-text failed: %s",
                    (message or "")[:400],
                )
                return self._force_or_fail(
                    path, tmp, context, message,
                )

            result = self._docling.extract(ocr_pdf, context)
            log.info(
                "ocr_docling: after --skip-text + docling: "
                "blocks=%d tables=%d warnings=%d garbled=%s",
                len(result.blocks),
                len(result.tables),
                len(result.warnings),
                _result_is_garbled(result),
            )
            result.notes.append("OCRmyPDF pre-processing applied")
            result.artifacts["ocr_pdf"] = str(ocr_pdf)

            if not (
                ocr_cfg.force_when_garbled
                and _result_is_garbled(result)
            ):
                return result

            log.info(
                "ocr_docling: retrying with OCRmyPDF --force-ocr"
            )
            forced_pdf = Path(tmp) / f"{path.stem}.forced.pdf"
            ok_force, force_msg = run_ocrmypdf(
                path, forced_pdf, ocr_cfg, force=True,
            )
            log.info(
                "ocr_docling: --force-ocr exit=%s, output_exists=%s",
                ok_force, forced_pdf.exists(),
            )
            if not ok_force:
                log.warning(
                    "ocr_docling: --force-ocr failed: %s",
                    (force_msg or "")[:400],
                )
                result.warnings.append(
                    "Garbled text layer detected but "
                    f"--force-ocr also failed: {(force_msg or '')[:400]}"
                )
                return result

            forced_ctx = replace(context, discard_garbled=False)
            forced_result = self._docling.extract(
                forced_pdf, forced_ctx,
            )
            log.info(
                "ocr_docling: after --force-ocr + docling: "
                "blocks=%d tables=%d warnings=%d",
                len(forced_result.blocks),
                len(forced_result.tables),
                len(forced_result.warnings),
            )
            forced_result.notes.append(
                "Garbled text layer detected; re-OCR'd with --force-ocr"
            )
            forced_result.artifacts["ocr_pdf"] = str(forced_pdf)
            if not forced_result.blocks and not forced_result.tables:
                forced_result.warnings.append(
                    "--force-ocr produced no extractable content; "
                    "check ocr.language (current="
                    f"{ocr_cfg.language!r}) and source PDF quality"
                )
            return forced_result

    def _force_or_fail(
        self,
        path: Path,
        tmp: str,
        context: ParserContext,
        skip_message: str,
    ) -> ParsedResult:
        ocr_cfg = context.config.ocr
        forced_pdf = Path(tmp) / f"{path.stem}.forced.pdf"
        ok_force, force_msg = run_ocrmypdf(
            path, forced_pdf, ocr_cfg, force=True,
        )
        if ok_force:
            forced_ctx = replace(context, discard_garbled=False)
            result = self._docling.extract(forced_pdf, forced_ctx)
            result.notes.append(
                "OCRmyPDF --force-ocr applied "
                "(initial --skip-text failed)"
            )
            result.artifacts["ocr_pdf"] = str(forced_pdf)
            return result
        result = self._docling.extract(path, context)
        result.warnings.append(
            "OCRmyPDF failed in both modes; "
            f"skip-text: {skip_message} | force: {force_msg}"
        )
        return result


def _result_is_garbled(result: ParsedResult) -> bool:
    for warning in result.warnings:
        if "garbled_text_layer" in warning:
            return True
    if not result.blocks:
        # Any empty extraction post-OCRmyPDF is worth a --force-ocr
        # retry. We already paid the OCR cost; runtime isn't crucial.
        return True
    for block in result.blocks:
        if looks_garbled(block.text):
            return True
    return False


def _max_block_ratio(result: ParsedResult) -> float:
    if not result.blocks:
        return 0.0
    return max(replacement_ratio(b.text) for b in result.blocks)
