from __future__ import annotations

from pathlib import Path

from localdataextractor.models import (
    ContentBlock,
    DocumentMetadata,
    ExtractionAttempt,
    NormalizedDocument,
    ParsedResult,
    RouteDecision,
)
from localdataextractor.parsers.common import blocks_to_title


def build_normalized_document(
    source_path: Path,
    parsed: ParsedResult,
    route_history: list[RouteDecision],
    attempts: list[ExtractionAttempt],
) -> NormalizedDocument:
    stat = source_path.stat()
    source = DocumentMetadata(
        source_path=str(source_path),
        file_size=stat.st_size,
        file_type=source_path.suffix.lower().lstrip("."),
    )

    title = blocks_to_title(parsed.blocks)
    by_type = _group_blocks(parsed.blocks)
    blocks_ordered = _ordered_blocks(parsed.blocks)

    overall_conf = attempts[-1].confidence.overall if attempts else 0.0
    block_conf = attempts[-1].confidence.block_scores if attempts else {}

    return NormalizedDocument(
        schema_version="1.0",
        source=source,
        document_metadata=parsed.metadata,
        extraction_attempts=attempts,
        route_history=route_history,
        overall_confidence=overall_conf,
        block_level_confidence=block_conf,
        title=title,
        headings=by_type["heading"],
        paragraphs=by_type["paragraph"],
        lists=by_type["list"],
        tables=parsed.tables,
        code_blocks=by_type["code"],
        block_quotes=by_type["blockquote"],
        figures=by_type["figure"],
        captions=by_type["caption"],
        blocks_ordered=blocks_ordered,
        warnings=parsed.warnings,
        notes=parsed.notes,
    )


def _ordered_blocks(blocks: list[ContentBlock]) -> list[dict[str, object]]:
    ordered: list[dict[str, object]] = []
    for block in blocks:
        payload: dict[str, object] = {
            "id": block.block_id,
            "type": block.block_type,
            "text": block.text,
            "confidence": block.confidence,
            "source": {
                "page": block.source.page,
                "sheet": block.source.sheet,
                "slide": block.source.slide,
                "file_offset": block.source.file_offset,
            },
            "meta": block.meta,
        }
        if block.heading_level:
            payload["level"] = block.heading_level
        ordered.append(payload)
    return ordered


def _group_blocks(blocks: list[ContentBlock]) -> dict[str, list[dict[str, object]]]:
    grouped = {
        "heading": [],
        "paragraph": [],
        "list": [],
        "code": [],
        "blockquote": [],
        "figure": [],
        "caption": [],
    }

    for block in blocks:
        payload: dict[str, object] = {
            "id": block.block_id,
            "text": block.text,
            "confidence": block.confidence,
            "source": {
                "page": block.source.page,
                "sheet": block.source.sheet,
                "slide": block.source.slide,
                "file_offset": block.source.file_offset,
            },
            "meta": block.meta,
        }
        if block.heading_level:
            payload["level"] = block.heading_level

        if block.block_type == "title":
            grouped["heading"].insert(0, payload)
        elif block.block_type in grouped:
            grouped[block.block_type].append(payload)

    return grouped
