from __future__ import annotations

from localdataextractor.models import NormalizedDocument, TableBlock


def render_markdown(document: NormalizedDocument) -> str:
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
