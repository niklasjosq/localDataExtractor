from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SourceReference:
    page: int | None = None
    sheet: str | None = None
    slide: int | None = None
    file_offset: int | None = None


@dataclass(slots=True)
class ContentBlock:
    block_id: str
    block_type: Literal[
        "title",
        "heading",
        "paragraph",
        "list",
        "table",
        "code",
        "blockquote",
        "figure",
        "caption",
    ]
    text: str = ""
    heading_level: int | None = None
    confidence: float = 0.0
    source: SourceReference = field(default_factory=SourceReference)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TableValidationIssue:
    code: str
    message: str
    severity: Literal["low", "medium", "high"] = "medium"


@dataclass(slots=True)
class TableBlock:
    table_id: str
    source: SourceReference = field(default_factory=SourceReference)
    caption: str | None = None
    header_rows: list[list[str]] = field(default_factory=list)
    body_rows: list[list[str]] = field(default_factory=list)
    column_count: int = 0
    row_count: int = 0
    merged_cells: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    validation_warnings: list[TableValidationIssue] = field(default_factory=list)


@dataclass(slots=True)
class RouteDecision:
    route_id: str
    parser: str
    reason: str
    detail: str = ""


@dataclass(slots=True)
class ConfidenceReport:
    overall: float
    block_scores: dict[str, float] = field(default_factory=dict)
    table_scores: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedResult:
    parser_name: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    blocks: list[ContentBlock] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    route_notes: list[str] = field(default_factory=list)
    scanned_hint: bool = False
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractionAttempt:
    timestamp: str
    route: str
    parser: str
    model: str | None
    confidence: ConfidenceReport
    reasons_for_retry: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentMetadata:
    source_path: str
    file_size: int
    file_type: str
    pages: int | None = None
    sheets: list[str] = field(default_factory=list)
    slides: int | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class NormalizedDocument:
    schema_version: str
    source: DocumentMetadata
    document_metadata: dict[str, Any] = field(default_factory=dict)
    extraction_attempts: list[ExtractionAttempt] = field(default_factory=list)
    route_history: list[RouteDecision] = field(default_factory=list)
    overall_confidence: float = 0.0
    block_level_confidence: dict[str, float] = field(default_factory=dict)
    title: str | None = None
    headings: list[dict[str, Any]] = field(default_factory=list)
    paragraphs: list[dict[str, Any]] = field(default_factory=list)
    lists: list[dict[str, Any]] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    code_blocks: list[dict[str, Any]] = field(default_factory=list)
    block_quotes: list[dict[str, Any]] = field(default_factory=list)
    figures: list[dict[str, Any]] = field(default_factory=list)
    captions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    below_threshold: bool = False


@dataclass(slots=True)
class FileState:
    source_path: str
    relative_path: str
    status: Literal[
        "pending",
        "processing",
        "completed",
        "completed_below_threshold",
        "failed",
    ] = "pending"
    retries: int = 0
    confidence: float = 0.0
    route: str = ""
    attempts: list[ExtractionAttempt] = field(default_factory=list)
    output_md: str | None = None
    output_json: str | None = None
    output_log: str | None = None
    last_error: str | None = None
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class JobState:
    schema_version: str
    job_id: str
    input_root: str
    output_root: str
    created_at: str
    updated_at: str
    files: dict[str, FileState] = field(default_factory=dict)


@dataclass(slots=True)
class VerificationReport:
    root: str
    total: int
    ok: int
    flagged: int
    failed: int
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IngestProgress:
    source_path: str
    status: str
    route: str = ""
    retries: int = 0
    confidence: float = 0.0
    message: str = ""


def dataclass_to_dict(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dataclass_fields__"):
        raw = asdict(obj)
        return {k: dataclass_to_dict(v) for k, v in raw.items()}
    if isinstance(obj, dict):
        return {k: dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dataclass_to_dict(v) for v in obj]
    return obj
