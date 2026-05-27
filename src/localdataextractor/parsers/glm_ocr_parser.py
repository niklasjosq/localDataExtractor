from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from localdataextractor.config import AppConfig
from localdataextractor.llm.client import LMStudioClient
from localdataextractor.models import (
    ContentBlock,
    ParsedResult,
    SourceReference,
    TableBlock,
)
from localdataextractor.parsers.base import ParserContext
from localdataextractor.quality.table_validation import validate_table
from localdataextractor.utils.image_preprocess import preprocess_for_ocr

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
}

SYSTEM_PROMPT = (
    "You are a precise document OCR engine. "
    "Extract all text, tables, and figures from the "
    "provided document page image.\n"
    "Preserve the original reading order of the page; "
    "for multi-column layouts, return blocks in left-to-right, "
    "top-to-bottom column order.\n"
    "Return JSON with exactly these keys:\n"
    '- "blocks": list of objects with keys '
    '"type" (one of "heading", "paragraph", "list", '
    '"code", "figure", "caption"), '
    '"text" (the extracted text), '
    '"heading_level" (int 1-6 or null), '
    '"reading_order" (int starting at 1)\n'
    '- "tables": list of objects with keys '
    '"caption" (string or null), '
    '"header_rows" (list of list of strings), '
    '"body_rows" (list of list of strings), '
    '"reading_order" (int)\n'
    "Preserve original text exactly, including punctuation, "
    "case and accents. Do not invent or omit content. "
    "Do not return commentary outside the JSON object."
)

TABLE_RETRY_PROMPT = (
    "You are a precise table OCR engine. "
    "The provided page image contains one or more tables that "
    "previously came out malformed. Re-extract ONLY the tables. "
    "Preserve every row and column exactly; do not merge or split "
    "cells; if a cell is empty, return an empty string. "
    "If you see a column header that spans multiple sub-columns, "
    "duplicate it across the sub-columns instead of leaving a hole.\n"
    "Return JSON with exactly one key:\n"
    '- "tables": list of objects with keys '
    '"caption" (string or null), '
    '"header_rows" (list of list of strings), '
    '"body_rows" (list of list of strings)\n'
    "Do not return any text outside the JSON object."
)


def _render_pdf_pages(
    path: Path, dpi: int, max_pages: int, use_pypdfium2: bool,
) -> tuple[list[Any], list[str]]:
    """Render PDF pages to PIL.Image objects."""
    warnings: list[str] = []
    images: list[Any] = []

    if use_pypdfium2:
        rendered, warn = _render_with_pypdfium2(
            path, dpi, max_pages,
        )
        warnings.extend(warn)
        if rendered:
            return rendered, warnings

    rendered, warn = _render_with_pdfplumber(
        path, dpi, max_pages,
    )
    warnings.extend(warn)
    return rendered, warnings


def _render_with_pypdfium2(
    path: Path, dpi: int, max_pages: int,
) -> tuple[list[Any], list[str]]:
    warnings: list[str] = []
    images: list[Any] = []
    try:
        import pypdfium2 as pdfium  # type: ignore
    except ImportError:
        return images, warnings

    try:
        pdf = pdfium.PdfDocument(str(path))
        page_count = len(pdf)
        if page_count > max_pages:
            warnings.append(
                f"PDF has {page_count} pages, "
                f"only first {max_pages} processed (configured cap)"
            )
        scale = dpi / 72.0
        for i in range(min(page_count, max_pages)):
            page = pdf[i]
            pil = page.render(scale=scale).to_pil()
            images.append(pil)
        pdf.close()
    except Exception as exc:
        warnings.append(f"pypdfium2 render failed: {exc}")
    return images, warnings


def _render_with_pdfplumber(
    path: Path, dpi: int, max_pages: int,
) -> tuple[list[Any], list[str]]:
    warnings: list[str] = []
    images: list[Any] = []
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        warnings.append(
            "pdfplumber not available for PDF page rendering"
        )
        return images, warnings

    try:
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            if page_count > max_pages:
                warnings.append(
                    f"PDF has {page_count} pages, "
                    f"capped at {max_pages}"
                )
            for page in pdf.pages[:max_pages]:
                img = page.to_image(resolution=dpi)
                images.append(img.original)
    except Exception as exc:
        warnings.append(f"pdfplumber render failed: {exc}")

    return images, warnings


def _encode_pil_png(image: Any) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _encode_image_file(path: Path) -> str:
    raw = path.read_bytes()
    return base64.b64encode(raw).decode("ascii")


def _load_pil_image(path: Path) -> Any:
    from PIL import Image  # type: ignore
    return Image.open(path).convert("RGB")


def _parse_blocks(
    raw_blocks: list[dict[str, Any]],
    page_num: int,
    block_prefix: str,
) -> list[ContentBlock]:
    ordered = sorted(
        enumerate(raw_blocks),
        key=lambda kv: (
            int(kv[1].get("reading_order", kv[0] + 1) or kv[0] + 1),
            kv[0],
        ),
    )
    blocks: list[ContentBlock] = []
    for new_idx, (_, item) in enumerate(ordered):
        btype = item.get("type", "paragraph")
        if btype not in (
            "heading", "paragraph", "list",
            "code", "figure", "caption",
        ):
            btype = "paragraph"
        text = str(item.get("text", ""))
        if not text.strip():
            continue
        heading_level = item.get("heading_level")
        if btype == "heading" and heading_level is not None:
            try:
                heading_level = int(heading_level)
            except (TypeError, ValueError):
                heading_level = None
        else:
            heading_level = None
        blocks.append(ContentBlock(
            block_id=f"{block_prefix}_b{new_idx}",
            block_type=btype,
            text=text,
            heading_level=heading_level,
            confidence=97.0,
            source=SourceReference(page=page_num),
        ))
    return blocks


def _parse_tables(
    raw_tables: list[dict[str, Any]],
    page_num: int,
    table_prefix: str,
) -> list[TableBlock]:
    tables: list[TableBlock] = []
    for i, item in enumerate(raw_tables):
        headers = item.get("header_rows", [])
        body = item.get("body_rows", [])
        caption = item.get("caption")
        header_rows = [
            [str(c) for c in row] for row in headers
        ]
        body_rows = [
            [str(c) for c in row] for row in body
        ]
        all_rows = header_rows + body_rows
        col_count = max(
            (len(r) for r in all_rows), default=0,
        )
        tables.append(TableBlock(
            table_id=f"{table_prefix}_t{i}",
            source=SourceReference(page=page_num),
            caption=(
                str(caption) if caption is not None else None
            ),
            header_rows=header_rows,
            body_rows=body_rows,
            column_count=col_count,
            row_count=len(body_rows),
            confidence=95.0,
        ))
    return tables


def _needs_table_retry(
    tables: list[TableBlock], cfg: AppConfig,
) -> bool:
    if not tables:
        return False
    threshold = cfg.retry.confidence_threshold
    for table in tables:
        if table.column_count <= 1:
            return True
        if table.row_count == 0:
            return True
        validation = validate_table(table, cfg.tables)
        if validation.score < threshold:
            return True
    return False


class GLMOCRParser:
    name = "glm_ocr"

    def extract(
        self, path: Path, context: ParserContext,
    ) -> ParsedResult:
        ext = path.suffix.lower()
        glm_cfg = context.config.glm_ocr
        preprocess_cfg = context.config.image_preprocess
        warnings: list[str] = []
        notes: list[str] = []

        if ext == ".pdf":
            images, render_warnings = _render_pdf_pages(
                path,
                glm_cfg.page_dpi,
                glm_cfg.max_pages,
                glm_cfg.use_pypdfium2,
            )
            warnings.extend(render_warnings)
            if not images:
                return ParsedResult(
                    parser_name=self.name,
                    warnings=warnings + [
                        "No pages rendered from PDF"
                    ],
                )
        elif ext in IMAGE_EXTENSIONS:
            try:
                images = [_load_pil_image(path)]
            except Exception as exc:
                return ParsedResult(
                    parser_name=self.name,
                    warnings=[f"Image read failed: {exc}"],
                )
        else:
            return ParsedResult(
                parser_name=self.name,
                warnings=[
                    f"glm_ocr does not support {ext} files; "
                    "use PDF or image input"
                ],
            )

        processed: list[Any] = []
        for idx, img in enumerate(images):
            try:
                pre_img, pre_notes = preprocess_for_ocr(
                    img, preprocess_cfg,
                )
                if pre_notes:
                    notes.append(
                        f"page{idx+1}_preprocess:{','.join(pre_notes)}"
                    )
                processed.append(pre_img)
            except Exception as exc:
                warnings.append(
                    f"page {idx+1} preprocess failed: {exc}"
                )
                processed.append(img)

        llm = LMStudioClient(context.config.llm)
        all_blocks: list[ContentBlock] = []
        all_tables: list[TableBlock] = []
        stem = path.stem

        for page_idx, img in enumerate(processed):
            page_num = page_idx + 1
            prefix = f"{stem}_p{page_num}"

            context.logger.info(
                "glm_ocr: processing page %d/%d",
                page_num, len(processed),
            )

            try:
                img_b64 = _encode_pil_png(img)
            except Exception as exc:
                warnings.append(
                    f"page {page_num} encode failed: {exc}"
                )
                continue

            response = llm.request_vision_ocr(
                model=glm_cfg.model_name,
                system_prompt=SYSTEM_PROMPT,
                user_text=(
                    f"OCR page {page_num} of this document. "
                    "Return structured JSON."
                ),
                images_b64=[img_b64],
                timeout=glm_cfg.timeout_seconds,
                temperature=glm_cfg.temperature_override,
            )

            if not response.ok:
                warnings.append(
                    f"Page {page_num} OCR failed: "
                    f"{response.error}"
                )
                continue

            data = response.content
            raw_blocks = data.get("blocks", [])
            raw_tables = data.get("tables", [])
            page_blocks: list[ContentBlock] = []
            page_tables: list[TableBlock] = []

            if isinstance(raw_blocks, list):
                page_blocks = _parse_blocks(
                    raw_blocks, page_num, prefix,
                )
            if isinstance(raw_tables, list):
                page_tables = _parse_tables(
                    raw_tables, page_num, prefix,
                )

            if (
                glm_cfg.table_retry_enabled
                and _needs_table_retry(
                    page_tables, context.config,
                )
            ):
                retry_tables, retry_warn = self._table_only_retry(
                    llm, img, page_num, prefix, context.config,
                )
                if retry_tables:
                    page_tables = retry_tables
                    notes.append(
                        f"page{page_num}_table_retry:applied"
                    )
                if retry_warn:
                    warnings.extend(retry_warn)

            all_blocks.extend(page_blocks)
            all_tables.extend(page_tables)

        return ParsedResult(
            parser_name=self.name,
            blocks=all_blocks,
            tables=all_tables,
            warnings=warnings,
            notes=notes,
            metadata={"glm_ocr_model": glm_cfg.model_name},
        )

    def _table_only_retry(
        self,
        llm: LMStudioClient,
        image: Any,
        page_num: int,
        prefix: str,
        cfg: AppConfig,
    ) -> tuple[list[TableBlock], list[str]]:
        warnings: list[str] = []
        try:
            from PIL import Image  # type: ignore
            scale = (
                cfg.glm_ocr.table_retry_dpi
                / max(cfg.glm_ocr.page_dpi, 1)
            )
            if scale > 1.01:
                w, h = image.size
                new_size = (int(w * scale), int(h * scale))
                image = image.resize(
                    new_size, resample=Image.LANCZOS,
                )
            img_b64 = _encode_pil_png(image)
        except Exception as exc:
            warnings.append(
                f"page {page_num} table-retry encode failed: {exc}"
            )
            return [], warnings

        response = llm.request_vision_ocr(
            model=cfg.glm_ocr.model_name,
            system_prompt=TABLE_RETRY_PROMPT,
            user_text=(
                f"Re-extract tables on page {page_num}. "
                "Return JSON."
            ),
            images_b64=[img_b64],
            timeout=cfg.glm_ocr.timeout_seconds,
            temperature=cfg.glm_ocr.temperature_override,
        )
        if not response.ok:
            warnings.append(
                f"page {page_num} table-retry failed: "
                f"{response.error}"
            )
            return [], warnings

        raw_tables = response.content.get("tables", [])
        if not isinstance(raw_tables, list):
            return [], warnings
        tables = _parse_tables(raw_tables, page_num, prefix)
        return tables, warnings
