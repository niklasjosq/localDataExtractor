from __future__ import annotations

from pathlib import Path
from typing import Any

from localdataextractor.models import ParsedResult, SourceReference, TableBlock
from localdataextractor.parsers.base import ParserContext
from localdataextractor.parsers.common import markdown_to_blocks_and_tables, plain_text_to_blocks
from localdataextractor.parsers.table_extractors import extract_tables_multi


class DoclingParser:
    name = "docling"

    def extract(self, path: Path, context: ParserContext) -> ParsedResult:
        warnings: list[str] = []
        route_notes: list[str] = []
        markdown_text = ""
        scanned_hint = False

        if path.suffix.lower() == ".pdf":
            scanned_hint = detect_scanned_pdf(path)
            route_notes.append(f"scanned_hint={scanned_hint}")

        try:
            from docling.document_converter import DocumentConverter  # type: ignore

            converter = DocumentConverter()
            result = converter.convert(str(path))
            document = getattr(result, "document", None)
            if document is not None:
                markdown_text = document.export_to_markdown()
            else:
                markdown_text = str(result)
        except Exception as exc:  # pragma: no cover - optional dependency path
            warnings.append(f"Docling unavailable/failed: {exc}")

        table_candidates: list[TableBlock] = []
        notes: list[str] = []
        if path.suffix.lower() == ".pdf":
            table_candidates, table_warnings, table_notes = (
                extract_tables_multi(path, context.config)
            )
            warnings.extend(table_warnings)
            notes.extend(table_notes)

        if markdown_text.strip():
            blocks, tables = markdown_to_blocks_and_tables(markdown_text)
            if table_candidates:
                tables = _replace_or_extend_tables(
                    tables, table_candidates,
                )
            return ParsedResult(
                parser_name=self.name,
                warnings=warnings,
                notes=notes,
                blocks=blocks,
                tables=tables,
                route_notes=route_notes,
                scanned_hint=scanned_hint,
            )

        fallback_text, fallback_warnings = _fallback_text_extract(path)
        warnings.extend(fallback_warnings)
        blocks = plain_text_to_blocks(fallback_text)
        return ParsedResult(
            parser_name=self.name,
            warnings=warnings,
            notes=notes,
            blocks=blocks,
            tables=table_candidates,
            route_notes=route_notes,
            scanned_hint=scanned_hint,
        )


def _replace_or_extend_tables(
    inline_tables: list[TableBlock],
    extracted: list[TableBlock],
) -> list[TableBlock]:
    """Prefer extracted (PDF-grounded) tables but keep inline ones
    that don't have a same-page peer in the extracted set."""
    extracted_pages = {
        t.source.page for t in extracted if t.source.page is not None
    }
    out = list(extracted)
    for inline in inline_tables:
        if inline.source.page not in extracted_pages:
            out.append(inline)
    for idx, t in enumerate(out, start=1):
        t.table_id = f"tbl_{idx:05d}"
    return out


def _fallback_text_extract(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            return text, warnings
        except Exception as exc:  # pragma: no cover
            warnings.append(f"pypdf fallback failed: {exc}")
    try:
        return path.read_text(encoding="utf-8", errors="replace"), warnings
    except Exception as exc:  # pragma: no cover
        warnings.append(f"text fallback failed: {exc}")
    return "", warnings


def detect_scanned_pdf(path: Path, sample_pages: int = 3) -> bool:
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return False
            checked = pdf.pages[:sample_pages]
            text_chars = 0
            image_count = 0
            for page in checked:
                text = page.extract_text() or ""
                text_chars += len(text.strip())
                image_count += len(page.images)
            return text_chars < 120 and image_count > 0
    except Exception:
        return False


def extract_pdf_tables_with_pdfplumber(path: Path) -> tuple[list[TableBlock], list[str]]:
    warnings: list[str] = []
    tables: list[TableBlock] = []
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(str(path)) as pdf:
            table_id = 0
            for page_index, page in enumerate(pdf.pages, start=1):
                extracted = page.extract_tables(
                    {
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "snap_tolerance": 3,
                        "join_tolerance": 3,
                    }
                )
                for raw in extracted:
                    if not raw:
                        continue
                    rows = [["" if c is None else str(c).strip() for c in row] for row in raw]
                    if not rows:
                        continue
                    headers = rows[0]
                    body = rows[1:]
                    table_id += 1
                    tables.append(
                        TableBlock(
                            table_id=f"tbl_{table_id:05d}",
                            source=SourceReference(page=page_index),
                            header_rows=[headers] if headers else [],
                            body_rows=body,
                            column_count=max(len(r) for r in rows),
                            row_count=len(body),
                            confidence=90.0,
                        )
                    )
    except Exception as exc:  # pragma: no cover
        warnings.append(f"pdfplumber table extraction failed: {exc}")
    return tables, warnings
