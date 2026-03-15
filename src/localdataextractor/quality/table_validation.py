from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from localdataextractor.config import TableConfig
from localdataextractor.models import TableBlock, TableValidationIssue


@dataclass(slots=True)
class TableValidationResult:
    score: float
    issues: list[TableValidationIssue]


def validate_table(table: TableBlock, config: TableConfig) -> TableValidationResult:
    issues: list[TableValidationIssue] = []
    score = 100.0

    rows = table.header_rows + table.body_rows
    if not rows:
        issues.append(TableValidationIssue(code="empty_table", message="Table has no rows", severity="high"))
        return TableValidationResult(score=0.0, issues=issues)

    expected_cols = max((len(row) for row in rows), default=0)
    table.column_count = expected_cols
    table.row_count = len(table.body_rows)

    inconsistent = sum(1 for row in rows if len(row) != expected_cols)
    if expected_cols <= 1:
        issues.append(
            TableValidationIssue(
                code="column_collapse_risk",
                message="Table has 1 or fewer columns",
                severity="high",
            )
        )
        score -= 20

    if config.strict_column_consistency and inconsistent:
        issues.append(
            TableValidationIssue(
                code="inconsistent_columns",
                message=f"{inconsistent} rows have inconsistent column count",
                severity="high",
            )
        )
        score -= min(30, 10 * inconsistent)

    header_score_penalty = _header_penalty(table.header_rows)
    if header_score_penalty > 0:
        issues.append(
            TableValidationIssue(
                code="weak_headers",
                message="Header row quality appears weak",
                severity="medium",
            )
        )
        score -= header_score_penalty

    duplicate_ratio = _duplicate_row_ratio(table.body_rows)
    if duplicate_ratio > config.max_duplicate_row_ratio:
        issues.append(
            TableValidationIssue(
                code="duplicate_rows",
                message=f"Duplicate row ratio too high: {duplicate_ratio:.2f}",
                severity="medium",
            )
        )
        score -= min(20, (duplicate_ratio - config.max_duplicate_row_ratio) * 120)

    empty_ratio = _empty_cell_ratio(rows)
    if empty_ratio > config.max_empty_ratio:
        issues.append(
            TableValidationIssue(
                code="empty_cell_anomaly",
                message=f"Empty cell ratio too high: {empty_ratio:.2f}",
                severity="medium",
            )
        )
        score -= min(20, (empty_ratio - config.max_empty_ratio) * 120)

    score = max(0.0, min(100.0, score))
    return TableValidationResult(score=score, issues=issues)


def _header_penalty(header_rows: list[list[str]]) -> float:
    if not header_rows:
        return 8.0
    header = header_rows[0]
    if not header:
        return 10.0
    non_empty = [cell for cell in header if cell.strip()]
    if not non_empty:
        return 12.0
    numeric_like = sum(1 for cell in non_empty if cell.replace(".", "", 1).isdigit())
    numeric_ratio = numeric_like / len(non_empty)
    if numeric_ratio > 0.6:
        return 8.0
    return 0.0


def _duplicate_row_ratio(rows: list[list[str]]) -> float:
    if not rows:
        return 0.0
    normalized = [tuple(cell.strip() for cell in row) for row in rows]
    unique = len(set(normalized))
    return max(0.0, 1.0 - unique / len(normalized))


def _empty_cell_ratio(rows: list[list[str]]) -> float:
    total = sum(len(row) for row in rows)
    if total == 0:
        return 1.0
    empty = sum(1 for row in rows for cell in row if not cell.strip())
    return empty / total
