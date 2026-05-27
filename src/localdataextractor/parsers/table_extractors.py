from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from localdataextractor.config import AppConfig
from localdataextractor.models import SourceReference, TableBlock
from localdataextractor.quality.table_validation import (
    TableValidationResult,
    validate_table,
)


@dataclass(slots=True)
class TableCandidate:
    """A table found by one strategy, with its grounding info."""
    table: TableBlock
    page: int
    bbox: tuple[float, float, float, float] | None
    strategy: str
    score: float
    issues: list[Any] = field(default_factory=list)


def extract_tables_multi(
    path: Path,
    config: AppConfig,
) -> tuple[list[TableBlock], list[str], list[str]]:
    """Run every enabled table extraction strategy and merge results.

    Returns (best_tables, warnings, notes). Notes describe which
    strategies ran and produced anything; warnings describe failures.
    """
    warnings: list[str] = []
    notes: list[str] = []
    candidates: list[TableCandidate] = []

    if config.table_extraction.pdfplumber_lines:
        cand, warn, note = _pdfplumber_strategy(
            path,
            strategy="lines",
            vertical="lines",
            horizontal="lines",
            label="pdfplumber_lines",
        )
        candidates.extend(cand)
        warnings.extend(warn)
        notes.extend(note)

    if config.table_extraction.pdfplumber_text:
        cand, warn, note = _pdfplumber_strategy(
            path,
            strategy="text",
            vertical="text",
            horizontal="text",
            label="pdfplumber_text",
        )
        candidates.extend(cand)
        warnings.extend(warn)
        notes.extend(note)

    if config.table_extraction.pdfplumber_lines_strict:
        cand, warn, note = _pdfplumber_strategy(
            path,
            strategy="lines_strict",
            vertical="lines_strict",
            horizontal="lines_strict",
            label="pdfplumber_lines_strict",
        )
        candidates.extend(cand)
        warnings.extend(warn)
        notes.extend(note)

    if config.table_extraction.camelot_lattice:
        cand, warn, note = _camelot_strategy(
            path, flavor="lattice",
        )
        candidates.extend(cand)
        warnings.extend(warn)
        notes.extend(note)

    if config.table_extraction.camelot_stream:
        cand, warn, note = _camelot_strategy(
            path, flavor="stream",
        )
        candidates.extend(cand)
        warnings.extend(warn)
        notes.extend(note)

    if not candidates:
        return [], warnings, notes

    for candidate in candidates:
        validation = validate_table(candidate.table, config.tables)
        candidate.score = validation.score
        candidate.issues = validation.issues

    candidates = [
        c for c in candidates
        if c.score >= config.table_extraction.min_table_score
    ]

    best = _merge_by_bbox(
        candidates,
        overlap_threshold=config.table_extraction.bbox_overlap_threshold,
    )

    renumbered: list[TableBlock] = []
    for idx, cand in enumerate(best, start=1):
        cand.table.table_id = f"tbl_{idx:05d}"
        cand.table.confidence = cand.score
        renumbered.append(cand.table)
        notes.append(
            f"selected:{cand.strategy}:p{cand.page}:"
            f"score={cand.score:.1f}"
        )

    return renumbered, warnings, notes


def _pdfplumber_strategy(
    path: Path,
    strategy: str,
    vertical: str,
    horizontal: str,
    label: str,
) -> tuple[list[TableCandidate], list[str], list[str]]:
    warnings: list[str] = []
    notes: list[str] = []
    out: list[TableCandidate] = []

    try:
        import pdfplumber  # type: ignore
    except ImportError:
        warnings.append(
            f"pdfplumber unavailable for {label} strategy"
        )
        return out, warnings, notes

    try:
        with pdfplumber.open(str(path)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                try:
                    settings = {
                        "vertical_strategy": vertical,
                        "horizontal_strategy": horizontal,
                        "snap_tolerance": 3,
                        "join_tolerance": 3,
                    }
                    found = page.find_tables(settings)
                except Exception as exc:
                    warnings.append(
                        f"{label} p{page_index} find_tables "
                        f"failed: {exc}"
                    )
                    continue

                for raw in found:
                    try:
                        rows = raw.extract()
                    except Exception:
                        continue
                    if not rows:
                        continue
                    cleaned = [
                        [
                            "" if c is None else str(c).strip()
                            for c in row
                        ]
                        for row in rows
                    ]
                    if not any(
                        any(cell for cell in row)
                        for row in cleaned
                    ):
                        continue
                    headers = cleaned[0]
                    body = cleaned[1:]
                    col_count = max(
                        (len(r) for r in cleaned), default=0,
                    )
                    table = TableBlock(
                        table_id=f"{label}_p{page_index}_"
                                  f"{len(out):03d}",
                        source=SourceReference(page=page_index),
                        header_rows=[headers] if headers else [],
                        body_rows=body,
                        column_count=col_count,
                        row_count=len(body),
                        confidence=0.0,
                    )
                    bbox = getattr(raw, "bbox", None)
                    out.append(TableCandidate(
                        table=table,
                        page=page_index,
                        bbox=tuple(bbox) if bbox else None,
                        strategy=label,
                        score=0.0,
                    ))
                if found:
                    notes.append(
                        f"{label}:p{page_index}:{len(found)}_found"
                    )
    except Exception as exc:
        warnings.append(f"{label} open failed: {exc}")

    return out, warnings, notes


def _camelot_strategy(
    path: Path, flavor: str,
) -> tuple[list[TableCandidate], list[str], list[str]]:
    warnings: list[str] = []
    notes: list[str] = []
    out: list[TableCandidate] = []
    label = f"camelot_{flavor}"

    try:
        import camelot  # type: ignore
    except ImportError:
        return out, warnings, notes

    try:
        tables = camelot.read_pdf(
            str(path), pages="all", flavor=flavor,
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "ghostscript" in msg or "no tables found" in msg:
            return out, warnings, notes
        warnings.append(f"{label} failed: {exc}")
        return out, warnings, notes

    for idx, camelot_table in enumerate(tables):
        try:
            df = camelot_table.df
            rows = df.values.tolist()
            if not rows:
                continue
            cleaned = [
                [
                    "" if v is None else str(v).strip()
                    for v in row
                ]
                for row in rows
            ]
            if not any(
                any(cell for cell in row) for row in cleaned
            ):
                continue
            headers = cleaned[0]
            body = cleaned[1:]
            col_count = max(
                (len(r) for r in cleaned), default=0,
            )
            page_num = int(
                getattr(camelot_table, "page", 0) or 0
            )
            bbox = None
            try:
                bbox_attr = camelot_table._bbox  # type: ignore
                bbox = tuple(bbox_attr) if bbox_attr else None
            except Exception:
                bbox = None
            table = TableBlock(
                table_id=f"{label}_p{page_num}_{idx:03d}",
                source=SourceReference(page=page_num),
                header_rows=[headers] if headers else [],
                body_rows=body,
                column_count=col_count,
                row_count=len(body),
                confidence=0.0,
            )
            out.append(TableCandidate(
                table=table,
                page=page_num,
                bbox=bbox,
                strategy=label,
                score=0.0,
            ))
        except Exception as exc:
            warnings.append(
                f"{label} table {idx} read failed: {exc}"
            )

    if out:
        notes.append(f"{label}:{len(out)}_tables")
    return out, warnings, notes


def _merge_by_bbox(
    candidates: list[TableCandidate],
    overlap_threshold: float,
) -> list[TableCandidate]:
    """Group candidates that refer to the same physical table and
    keep the highest-scoring one per group.

    Grouping rule: same page AND (bboxes overlap by >= threshold OR
    one of them has no bbox AND row counts are within 20%).
    """
    by_page: dict[int, list[TableCandidate]] = {}
    for cand in candidates:
        by_page.setdefault(cand.page, []).append(cand)

    selected: list[TableCandidate] = []
    for page, page_cands in by_page.items():
        page_cands.sort(key=lambda c: c.score, reverse=True)
        used: list[TableCandidate] = []
        for cand in page_cands:
            duplicate = False
            for picked in used:
                if _candidates_overlap(
                    cand, picked, overlap_threshold,
                ):
                    duplicate = True
                    break
            if not duplicate:
                used.append(cand)
        selected.extend(used)
    return selected


def _candidates_overlap(
    a: TableCandidate,
    b: TableCandidate,
    threshold: float,
) -> bool:
    if a.bbox and b.bbox:
        return _bbox_iou(a.bbox, b.bbox) >= threshold
    rows_a = max(a.table.row_count, 1)
    rows_b = max(b.table.row_count, 1)
    ratio = min(rows_a, rows_b) / max(rows_a, rows_b)
    cols_a = max(a.table.column_count, 1)
    cols_b = max(b.table.column_count, 1)
    col_ratio = min(cols_a, cols_b) / max(cols_a, cols_b)
    return ratio >= 0.8 and col_ratio >= 0.8


def _bbox_iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union
