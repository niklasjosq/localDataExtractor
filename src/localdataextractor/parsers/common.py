from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from localdataextractor.models import ContentBlock, SourceReference, TableBlock


def _next_id(prefix: str, index: int) -> str:
    return f"{prefix}_{index:05d}"


def plain_text_to_blocks(text: str, kind: str = "paragraph") -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", text) if segment.strip()]
    for idx, paragraph in enumerate(paragraphs):
        blocks.append(
            ContentBlock(
                block_id=_next_id("blk", idx + 1),
                block_type=kind,  # type: ignore[arg-type]
                text=paragraph,
                confidence=96.0,
            )
        )
    if not blocks and text.strip():
        blocks.append(
            ContentBlock(
                block_id=_next_id("blk", 1),
                block_type="paragraph",
                text=text.strip(),
                confidence=85.0,
            )
        )
    return blocks


def markdown_to_blocks_and_tables(markdown: str) -> tuple[list[ContentBlock], list[TableBlock]]:
    blocks: list[ContentBlock] = []
    tables: list[TableBlock] = []

    lines = markdown.splitlines()
    i = 0
    block_index = 0
    table_index = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue

        if line.startswith("```"):
            fence = line[:3]
            code_lines = [line]
            i += 1
            while i < len(lines):
                code_lines.append(lines[i])
                if lines[i].startswith(fence):
                    i += 1
                    break
                i += 1
            block_index += 1
            blocks.append(
                ContentBlock(
                    block_id=_next_id("blk", block_index),
                    block_type="code",
                    text="\n".join(code_lines),
                    confidence=95.0,
                )
            )
            continue

        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            text = line[level:].strip()
            block_type = "title" if level == 1 and block_index == 0 else "heading"
            block_index += 1
            blocks.append(
                ContentBlock(
                    block_id=_next_id("blk", block_index),
                    block_type=block_type,  # type: ignore[arg-type]
                    text=text,
                    heading_level=level,
                    confidence=97.0,
                )
            )
            i += 1
            continue

        if line.startswith(">"):
            quote_lines = [line[1:].strip()]
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                quote_lines.append(lines[i][1:].strip())
                i += 1
            block_index += 1
            blocks.append(
                ContentBlock(
                    block_id=_next_id("blk", block_index),
                    block_type="blockquote",
                    text="\n".join(quote_lines),
                    confidence=95.0,
                )
            )
            continue

        if re.match(r"^\s*[-*+]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            list_lines = [line]
            i += 1
            while i < len(lines) and (
                re.match(r"^\s*[-*+]\s+", lines[i])
                or re.match(r"^\s*\d+\.\s+", lines[i])
            ):
                list_lines.append(lines[i])
                i += 1
            block_index += 1
            blocks.append(
                ContentBlock(
                    block_id=_next_id("blk", block_index),
                    block_type="list",
                    text="\n".join(list_lines),
                    confidence=95.0,
                )
            )
            continue

        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*[-:]+", lines[i + 1]):
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i]:
                table_lines.append(lines[i])
                i += 1
            table = markdown_table_to_structured(table_lines, table_index + 1)
            table_index += 1
            tables.append(table)
            block_index += 1
            blocks.append(
                ContentBlock(
                    block_id=_next_id("blk", block_index),
                    block_type="table",
                    text="\n".join(table_lines),
                    confidence=table.confidence,
                    meta={"table_id": table.table_id},
                )
            )
            continue

        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("#"):
            if lines[i].startswith(">") or lines[i].startswith("```"):
                break
            if re.match(r"^\s*[-*+]\s+", lines[i]) or re.match(r"^\s*\d+\.\s+", lines[i]):
                break
            if "|" in lines[i] and i + 1 < len(lines) and re.match(r"^\s*\|?\s*[-:]+", lines[i + 1]):
                break
            para_lines.append(lines[i])
            i += 1

        block_index += 1
        blocks.append(
            ContentBlock(
                block_id=_next_id("blk", block_index),
                block_type="paragraph",
                text="\n".join(para_lines).strip(),
                confidence=94.0,
            )
        )

    return blocks, tables


def markdown_table_to_structured(lines: Iterable[str], index: int) -> TableBlock:
    normalized = [line.strip().strip("|") for line in lines]
    split_rows = [[cell.strip() for cell in row.split("|")] for row in normalized]
    header = split_rows[0] if split_rows else []
    body = split_rows[2:] if len(split_rows) > 2 else []
    col_count = max([len(row) for row in split_rows], default=0)
    row_count = len(body)
    return TableBlock(
        table_id=f"tbl_{index:05d}",
        source=SourceReference(),
        header_rows=[header] if header else [],
        body_rows=body,
        column_count=col_count,
        row_count=row_count,
        confidence=90.0,
    )


def blocks_to_title(blocks: list[ContentBlock]) -> str | None:
    for block in blocks:
        if block.block_type == "title" and block.text.strip():
            return block.text.strip()
    for block in blocks:
        if block.block_type == "heading" and block.text.strip():
            return block.text.strip()
    for block in blocks:
        if block.block_type == "paragraph" and block.text.strip():
            return block.text.strip().splitlines()[0][:120]
    return None
