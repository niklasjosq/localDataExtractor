from __future__ import annotations

from localdataextractor.models import NormalizedDocument, TableBlock


def render_markdown(document: NormalizedDocument) -> str:
    if document.blocks_ordered:
        rendered = _render_ordered(document)
    else:
        rendered = _render_grouped(document)
    if rendered.strip():
        return rendered
    return _render_empty_diagnostic(document)


def _render_empty_diagnostic(document: NormalizedDocument) -> str:
    lines: list[str] = [
        "# (No content extracted)",
        "",
        (
            "The extraction pipeline produced no readable content "
            "for this document."
        ),
        "",
        f"- Source: `{document.source.source_path}`",
        f"- File type: `{document.source.file_type}`",
        (
            "- Overall confidence: "
            f"{document.overall_confidence:.2f}"
        ),
        f"- Below threshold: {document.below_threshold}",
    ]
    routes = [r.route_id for r in document.route_history]
    if routes:
        lines.append(f"- Routes attempted: {', '.join(routes)}")
    if document.warnings:
        lines.append("")
        lines.append("## Warnings")
        for warning in document.warnings:
            lines.append(f"- {warning}")
    if document.notes:
        lines.append("")
        lines.append("## Notes")
        for note in document.notes:
            lines.append(f"- {note}")
    lines.append("")
    lines.append(
        "See the sibling `.log` and `.json` files for full attempt "
        "history. Common causes: scanned PDF with wrong "
        "`ocr.language`, missing OCRmyPDF / Tesseract install, or "
        "Docling failing on this document."
    )
    return "\n".join(lines).strip() + "\n"


def _render_ordered(document: NormalizedDocument) -> str:
    lines: list[str] = []

    if document.title:
        lines.append(f"# {document.title}")
        lines.append("")

    tables_by_id: dict[str, TableBlock] = {
        t.table_id: t for t in document.tables
    }
    consumed_table_ids: set[str] = set()

    for block in document.blocks_ordered:
        btype = str(block.get("type", "paragraph"))
        text = str(block.get("text", "")).strip()
        if btype == "title" and document.title and text == document.title:
            continue
        if btype == "table":
            meta = block.get("meta") or {}
            table_id = (
                meta.get("table_id") if isinstance(meta, dict) else None
            )
            table = tables_by_id.get(table_id) if table_id else None
            if table is not None:
                lines.extend(render_table_markdown(table))
                consumed_table_ids.add(table.table_id)
                lines.append("")
            elif text:
                lines.append(text)
                lines.append("")
            continue
        if not text:
            continue
        if btype in {"title", "heading"}:
            level = int(
                block.get("level", 1 if btype == "title" else 2)
            )
            level = max(1, min(level, 6))
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        elif btype == "list":
            lines.extend(text.splitlines())
            lines.append("")
        elif btype == "code":
            if text.startswith("```"):
                lines.append(text)
            else:
                lines.append("```")
                lines.append(text)
                lines.append("```")
            lines.append("")
        elif btype == "blockquote":
            for row in text.splitlines():
                lines.append(f"> {row}")
            lines.append("")
        elif btype == "figure":
            lines.append(f"![figure]({text})")
            lines.append("")
        elif btype == "caption":
            lines.append(f"_{text}_")
            lines.append("")
        else:
            lines.append(text)
            lines.append("")

    for table in document.tables:
        if table.table_id in consumed_table_ids:
            continue
        lines.extend(render_table_markdown(table))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _render_grouped(document: NormalizedDocument) -> str:
    lines: list[str] = []

    if document.title:
        lines.append(f"# {document.title}")
        lines.append("")

    for heading in document.headings:
        level = int(heading.get("level", 2))
        text = str(heading.get("text", "")).strip()
        if text:
            lines.append(f"{'#' * max(1, min(level, 6))} {text}")
            lines.append("")

    for paragraph in document.paragraphs:
        text = str(paragraph.get("text", "")).strip()
        if text:
            lines.append(text)
            lines.append("")

    for item in document.lists:
        text = str(item.get("text", "")).strip()
        if text:
            lines.extend(text.splitlines())
            lines.append("")

    if document.tables:
        for table in document.tables:
            lines.extend(render_table_markdown(table))
            lines.append("")

    for code in document.code_blocks:
        text = str(code.get("text", "")).strip()
        if text:
            if text.startswith("```"):
                lines.append(text)
            else:
                lines.append("```")
                lines.append(text)
                lines.append("```")
            lines.append("")

    for quote in document.block_quotes:
        text = str(quote.get("text", "")).strip()
        if text:
            for row in text.splitlines():
                lines.append(f"> {row}")
            lines.append("")

    for figure in document.figures:
        text = str(figure.get("text", "")).strip()
        if text:
            lines.append(f"![figure]({text})")
            lines.append("")

    for caption in document.captions:
        text = str(caption.get("text", "")).strip()
        if text:
            lines.append(f"_{text}_")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_table_markdown(table: TableBlock) -> list[str]:
    lines: list[str] = []
    if table.caption:
        lines.append(f"**{table.caption}**")

    header = table.header_rows[0] if table.header_rows else []
    body = table.body_rows
    col_count = max([table.column_count, len(header)] + [len(row) for row in body])

    if col_count <= 0:
        lines.append("_Empty table_")
        return lines

    if not header:
        header = [f"Column {i + 1}" for i in range(col_count)]

    header = _pad_row(header, col_count)
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")

    if body:
        for row in body:
            padded = _pad_row(row, col_count)
            lines.append("| " + " | ".join(padded) + " |")
    else:
        lines.append("| " + " | ".join([""] * col_count) + " |")

    return lines


def _pad_row(row: list[str], target: int) -> list[str]:
    values = [str(cell) for cell in row[:target]]
    if len(values) < target:
        values.extend([""] * (target - len(values)))
    return values
