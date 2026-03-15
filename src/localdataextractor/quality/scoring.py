from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from localdataextractor.config import AppConfig
from localdataextractor.models import ConfidenceReport, ParsedResult, TableBlock
from localdataextractor.quality.table_validation import TableValidationResult, validate_table


@dataclass(slots=True)
class ScoringResult:
    report: ConfidenceReport
    table_results: dict[str, TableValidationResult]
    weak_extraction: bool


IMPORTANT_TABLE_TYPES = {"xls", "xlsx", "pdf"}


def score_extraction(parsed: ParsedResult, config: AppConfig, extension: str) -> ScoringResult:
    block_scores: dict[str, list[float]] = defaultdict(list)
    for block in parsed.blocks:
        block_scores[block.block_type].append(block.confidence)

    block_avg = {
        block_type: round(sum(scores) / len(scores), 2)
        for block_type, scores in block_scores.items()
        if scores
    }

    table_scores: dict[str, float] = {}
    table_results: dict[str, TableValidationResult] = {}
    for table in parsed.tables:
        validation = validate_table(table, config.tables)
        table.confidence = validation.score
        table.validation_warnings = validation.issues
        table_scores[table.table_id] = validation.score
        table_results[table.table_id] = validation

    text_length = sum(len(block.text) for block in parsed.blocks)
    weak_extraction = text_length < config.routing.min_characters_for_good_extraction

    base = 100.0
    warning_penalty = min(20.0, len(parsed.warnings) * 3.0)
    weak_penalty = 12.0 if weak_extraction else 0.0
    no_blocks_penalty = 25.0 if not parsed.blocks else 0.0

    block_penalty = 0.0
    if block_avg:
        avg_block_conf = sum(block_avg.values()) / len(block_avg)
        block_penalty = max(0.0, 100.0 - avg_block_conf) * 0.4

    table_penalty = 0.0
    if table_scores:
        avg_table = sum(table_scores.values()) / len(table_scores)
        table_penalty = max(0.0, 100.0 - avg_table) * 0.8

    overall = max(0.0, min(100.0, base - warning_penalty - weak_penalty - no_blocks_penalty - block_penalty - table_penalty))

    report = ConfidenceReport(
        overall=round(overall, 2),
        block_scores={k: round(v, 2) for k, v in block_avg.items()},
        table_scores={k: round(v, 2) for k, v in table_scores.items()},
    )
    return ScoringResult(report=report, table_results=table_results, weak_extraction=weak_extraction)


def needs_retry(
    report: ConfidenceReport,
    extension: str,
    config: AppConfig,
    tables: list[TableBlock],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    threshold = config.retry.confidence_threshold

    if report.overall < threshold:
        reasons.append(f"overall_confidence_below_threshold:{report.overall:.2f}<{threshold:.2f}")

    for table in tables:
        important = table.row_count >= config.tables.important_row_min or extension.lstrip(".") in IMPORTANT_TABLE_TYPES
        if important and table.confidence < threshold:
            reasons.append(
                f"important_table_below_threshold:{table.table_id}:{table.confidence:.2f}<{threshold:.2f}"
            )

    return (len(reasons) > 0), reasons
