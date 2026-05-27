from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import traceback
from typing import Callable, Iterable

from localdataextractor.config import AppConfig
from localdataextractor.llm import LMStudioClient
from localdataextractor.models import (
    ExtractionAttempt,
    FileState,
    IngestProgress,
    NormalizedDocument,
    ParsedResult,
    RouteDecision,
    dataclass_to_dict,
    utc_now_iso,
)
from localdataextractor.normalize import build_normalized_document
from localdataextractor.parsers import ParserContext, ParserManager
from localdataextractor.quality import needs_retry, score_extraction
from localdataextractor.render import render_markdown
from localdataextractor.router import explain_routes, get_file_info, plan_routes
from localdataextractor.state import JobStateStore
from localdataextractor.utils.filesystem import ensure_dir, find_input_files, safe_relpath
from localdataextractor.utils.json_io import write_json
from localdataextractor.utils.logging_utils import build_file_logger, setup_console_logger

ProgressCallback = Callable[[IngestProgress], None]


class IngestionPipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.logger = setup_console_logger(config.logging.level)
        self.parser_manager = ParserManager()
        self.llm_client = LMStudioClient(config.llm)

    def ingest(
        self,
        input_path: Path,
        output_root: Path,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        dry_run: bool = False,
        max_workers: int | None = None,
        explain_route: bool = False,
        state_path: Path | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        input_path = input_path.resolve()
        output_root = output_root.resolve()
        ensure_dir(output_root)

        include = include_globs or self.config.processing.include_globs
        exclude = exclude_globs or self.config.processing.exclude_globs
        files = find_input_files(input_path, include, exclude)

        root = input_path if input_path.is_dir() else input_path.parent
        state_file = state_path or output_root / "job_state.json"
        store = JobStateStore(state_file)
        state = store.create(root, output_root, files)

        if dry_run:
            for file in files:
                routes = plan_routes(get_file_info(file), self.config)
                detail = explain_routes(routes)
                self.logger.info("[dry-run] %s\n%s", file, detail)
                if progress_callback:
                    progress_callback(
                        IngestProgress(
                            source_path=str(file),
                            status="dry-run",
                            route=routes[0].route_id if routes else "",
                            message=detail,
                        )
                    )
            return state_file

        worker_count = max_workers or self.config.processing.max_workers
        worker_count = max(1, worker_count)
        lock = threading.Lock()

        def process(file: Path) -> None:
            relative = str(file.resolve().relative_to(root.resolve()))
            current = state.files[relative]
            current = replace(current, status="processing")
            with lock:
                store.update_file(state, relative, current)
            if progress_callback:
                progress_callback(IngestProgress(source_path=current.source_path, status="processing"))

            try:
                result_state = self._process_single_file(
                    file=file,
                    input_root=root,
                    output_root=output_root,
                    explain_route=explain_route,
                    prior_state=current,
                    progress_callback=progress_callback,
                )
            except Exception as exc:
                tb = traceback.format_exc()
                self.logger.error("Failed processing %s: %s", file, exc)
                failed = replace(
                    current,
                    status="failed",
                    last_error=f"{exc}\n{tb}",
                )
                with lock:
                    store.update_file(state, relative, failed)
                if progress_callback:
                    progress_callback(
                        IngestProgress(
                            source_path=current.source_path,
                            status="failed",
                            message=str(exc),
                        )
                    )
                return

            with lock:
                store.update_file(state, relative, result_state)

            if progress_callback:
                status_message = (
                    "output emitted below threshold"
                    if result_state.status == "completed_below_threshold"
                    else ""
                )
                progress_callback(
                    IngestProgress(
                        source_path=result_state.source_path,
                        status=result_state.status,
                        route=result_state.route,
                        retries=result_state.retries,
                        confidence=result_state.confidence,
                        message=status_message,
                    )
                )

        if worker_count == 1:
            for file in files:
                process(file)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(process, file) for file in files]
                for future in as_completed(futures):
                    future.result()

        return state_file

    def resume(
        self,
        state_path: Path,
        explain_route: bool = False,
        max_workers: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        store = JobStateStore(state_path)
        state = store.load()
        input_root = Path(state.input_root)
        output_root = Path(state.output_root)
        worker_count = max_workers or self.config.processing.max_workers
        worker_count = max(1, worker_count)
        lock = threading.Lock()

        pending = [
            Path(file_state.source_path)
            for file_state in state.files.values()
            if file_state.status in {"pending", "processing", "failed"}
        ]

        def process(file: Path) -> None:
            relative = str(file.resolve().relative_to(input_root.resolve()))
            current = state.files[relative]
            current = replace(current, status="processing")
            with lock:
                store.update_file(state, relative, current)
            if progress_callback:
                progress_callback(IngestProgress(source_path=current.source_path, status="processing"))

            try:
                result_state = self._process_single_file(
                    file=file,
                    input_root=input_root,
                    output_root=output_root,
                    explain_route=explain_route,
                    prior_state=current,
                    progress_callback=progress_callback,
                )
            except Exception as exc:
                tb = traceback.format_exc()
                failed = replace(
                    current,
                    status="failed",
                    last_error=f"{exc}\n{tb}",
                )
                with lock:
                    store.update_file(state, relative, failed)
                if progress_callback:
                    progress_callback(
                        IngestProgress(
                            source_path=current.source_path,
                            status="failed",
                            message=str(exc),
                        )
                    )
                return

            with lock:
                store.update_file(state, relative, result_state)
            if progress_callback:
                status_message = (
                    "output emitted below threshold"
                    if result_state.status == "completed_below_threshold"
                    else ""
                )
                progress_callback(
                    IngestProgress(
                        source_path=result_state.source_path,
                        status=result_state.status,
                        route=result_state.route,
                        retries=result_state.retries,
                        confidence=result_state.confidence,
                        message=status_message,
                    )
                )

        if worker_count == 1:
            for file in pending:
                process(file)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(process, file) for file in pending]
                for future in as_completed(futures):
                    future.result()

        return state_path

    def _process_single_file(
        self,
        file: Path,
        input_root: Path,
        output_root: Path,
        explain_route: bool,
        prior_state: FileState,
        progress_callback: ProgressCallback | None,
    ) -> FileState:
        file_info = get_file_info(file)
        routes = plan_routes(file_info, self.config)

        relative_path = safe_relpath(file, input_root)
        out_dir = ensure_dir(output_root / relative_path.parent)
        stem = relative_path.stem
        md_path = out_dir / f"{stem}.md"
        json_path = out_dir / f"{stem}.json"
        log_path = out_dir / f"{stem}.log"
        debug_dir = ensure_dir(out_dir / "_debug")

        file_logger = build_file_logger(log_path, self.config.logging.level)
        if explain_route:
            file_logger.info(explain_routes(routes))

        best_doc: NormalizedDocument | None = None
        best_conf = -1.0
        best_status = "failed"
        best_route = ""
        retries = 0
        attempts: list[ExtractionAttempt] = list(prior_state.attempts)
        route_history: list[RouteDecision] = []

        is_highest_accuracy = (
            self.config.routing.extraction_mode == "highest_accuracy"
        )
        max_attempts = (
            len(routes) if is_highest_accuracy
            else self.config.retry.max_route_attempts
        )

        for route_index, route in enumerate(routes[:max_attempts], start=1):
            route_history.append(route)
            if progress_callback:
                progress_callback(
                    IngestProgress(
                        source_path=str(file),
                        status="attempt",
                        route=route.route_id,
                        retries=retries,
                        message=f"attempt {route_index}/{max_attempts} parser={route.parser}",
                    )
                )

            with tempfile.TemporaryDirectory(prefix="localdataextractor-step-") as tmp_dir:
                context = ParserContext(
                    config=self.config,
                    temp_dir=Path(tmp_dir),
                    logger=file_logger,
                    route_id=route.route_id,
                    debug_dir=debug_dir,
                )
                parsed = self.parser_manager.extract(route.parser, file, context)

            if not parsed.blocks and not parsed.tables:
                parsed.warnings.append("No extractable content produced in this attempt")

            scoring = score_extraction(parsed, self.config, file.suffix.lower().lstrip("."))

            if self.config.llm.enable_vlm_repair and parsed.tables:
                parsed, llm_warnings = self._attempt_table_repair(parsed, file_logger)
                if llm_warnings:
                    parsed.warnings.extend(llm_warnings)
                scoring = score_extraction(parsed, self.config, file.suffix.lower().lstrip("."))

            retry_needed, retry_reasons = needs_retry(
                scoring.report,
                file.suffix.lower(),
                self.config,
                parsed.tables,
            )

            attempt = ExtractionAttempt(
                timestamp=utc_now_iso(),
                route=route.route_id,
                parser=parsed.parser_name,
                model=self.config.llm.primary_model if parsed.tables and self.config.llm.enable_vlm_repair else None,
                confidence=scoring.report,
                reasons_for_retry=retry_reasons,
                warnings=parsed.warnings,
                artifacts=parsed.artifacts,
            )
            attempts.append(attempt)

            doc = build_normalized_document(
                source_path=file,
                parsed=parsed,
                route_history=route_history,
                attempts=attempts,
            )
            doc.overall_confidence = scoring.report.overall
            doc.block_level_confidence = scoring.report.block_scores
            doc.below_threshold = retry_needed

            file_logger.info(
                "Attempt %d/%d route=%s parser=%s conf=%.2f retry=%s reasons=%s",
                route_index,
                len(routes),
                route.route_id,
                parsed.parser_name,
                scoring.report.overall,
                retry_needed,
                ",".join(retry_reasons),
            )

            if scoring.report.overall > best_conf:
                best_conf = scoring.report.overall
                best_doc = doc
                best_route = route.route_id

            if not retry_needed:
                best_status = "completed"
                best_doc = doc
                best_conf = scoring.report.overall
                best_route = route.route_id
                if not is_highest_accuracy:
                    break

            retries += 1

        if best_doc is None:
            return replace(
                prior_state,
                status="failed",
                retries=retries,
                route=best_route,
                confidence=0.0,
                output_md=str(md_path),
                output_json=str(json_path),
                output_log=str(log_path),
                last_error="No extraction attempt succeeded",
                attempts=attempts,
            )

        if best_status != "completed":
            best_status = "completed_below_threshold"
            best_doc.below_threshold = True

        markdown = render_markdown(best_doc)
        file_logger.info(
            "Writing markdown: best_route=%s best_conf=%.2f "
            "blocks=%d tables=%d md_chars=%d",
            best_route,
            best_conf,
            len(best_doc.blocks_ordered),
            len(best_doc.tables),
            len(markdown),
        )
        write_json(json_path, dataclass_to_dict(best_doc))
        md_path.write_text(markdown, encoding="utf-8")

        return replace(
            prior_state,
            status=best_status,
            retries=retries,
            confidence=best_conf,
            route=best_route,
            output_md=str(md_path),
            output_json=str(json_path),
            output_log=str(log_path),
            last_error=None,
            attempts=attempts,
        )

    def _attempt_table_repair(
        self,
        parsed: ParsedResult,
        file_logger,
    ) -> tuple[ParsedResult, list[str]]:
        warnings: list[str] = []
        threshold = self.config.retry.confidence_threshold

        for _ in range(self.config.retry.table_repair_attempts):
            repaired_any = False
            for table in parsed.tables:
                if table.confidence >= threshold:
                    continue
                repaired, error = self.llm_client.repair_table(table)
                if error:
                    warnings.append(f"LM repair failed for {table.table_id}: {error}")
                    continue
                table.header_rows = repaired.header_rows
                table.body_rows = repaired.body_rows
                table.caption = repaired.caption
                table.column_count = repaired.column_count
                table.row_count = repaired.row_count
                repaired_any = True
                file_logger.info("LM-based table repair applied to %s", table.table_id)
            if not repaired_any:
                break

        return parsed, warnings
