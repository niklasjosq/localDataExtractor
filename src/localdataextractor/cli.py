from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import threading
from typing import Callable

from localdataextractor.config import ConfigError, load_config, write_sample_config
from localdataextractor.llm import LMStudioClient
from localdataextractor.models import IngestProgress
from localdataextractor.pipeline import IngestionPipeline
from localdataextractor.utils.dependency_checks import run_startup_validation
from localdataextractor.verify import verify_output_tree


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="localdataextractor", description="Local document to Markdown pipeline")
    parser.add_argument("--config", type=Path, default=None, help="Path to TOML config")

    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest file/folder into Markdown+JSON+logs")
    ingest.add_argument("input", type=Path)
    ingest.add_argument("output", type=Path)
    ingest.add_argument("--include", action="append", default=[])
    ingest.add_argument("--exclude", action="append", default=[])
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument("--verbose", action="store_true")
    ingest.add_argument("--max-workers", type=int, default=None)
    ingest.add_argument("--explain-route", action="store_true")

    resume = sub.add_parser("resume", help="Resume from job_state.json")
    resume.add_argument("job_state", type=Path)
    resume.add_argument("--verbose", action="store_true")
    resume.add_argument("--max-workers", type=int, default=None)
    resume.add_argument("--explain-route", action="store_true")

    verify = sub.add_parser("verify", help="Verify output artifacts")
    verify.add_argument("output", type=Path)

    sub.add_parser("check-llm", help="Check local LM Studio connectivity")

    init_config = sub.add_parser("init-config", help="Write sample config TOML")
    init_config.add_argument("path", type=Path)

    return parser


def _print_startup_check(config) -> None:
    result = run_startup_validation(config)
    print("Startup validation:")
    for status in result.statuses:
        icon = "OK" if status.available else "MISS"
        req = "required" if status.required else "optional"
        print(f"- [{icon}] {status.name} ({req}): {status.detail}")


def _build_progress_printer() -> Callable[[IngestProgress], None]:
    lock = threading.Lock()
    terminal_statuses = {"completed", "completed_below_threshold", "failed"}
    seen_terminal: set[str] = set()
    totals = {"completed": 0, "completed_below_threshold": 0, "failed": 0}

    def on_progress(progress: IngestProgress) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        route = progress.route or "-"
        show_confidence = progress.status in terminal_statuses or progress.confidence > 0
        confidence = f"{float(progress.confidence):.2f}" if show_confidence else "-"
        message = " ".join(progress.message.split())
        message_part = f" | msg={message}" if message else ""
        line = (
            f"[{timestamp}] [{progress.status}] {progress.source_path} | "
            f"route={route} retries={progress.retries} conf={confidence}{message_part}"
        )

        summary_line = ""
        if progress.status in terminal_statuses and progress.source_path not in seen_terminal:
            seen_terminal.add(progress.source_path)
            totals[progress.status] += 1
            summary_line = (
                f"[{timestamp}] [summary] done={len(seen_terminal)} "
                f"ok={totals['completed']} "
                f"below_threshold={totals['completed_below_threshold']} "
                f"failed={totals['failed']}"
            )

        with lock:
            print(line)
            if summary_line:
                print(summary_line)

    return on_progress


def cmd_ingest(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.verbose:
        config.logging.level = "DEBUG"
    _print_startup_check(config)

    pipeline = IngestionPipeline(config)
    progress_callback = _build_progress_printer()
    print("Processing progress:")
    state_file = pipeline.ingest(
        input_path=args.input,
        output_root=args.output,
        include_globs=args.include or None,
        exclude_globs=args.exclude or None,
        dry_run=args.dry_run,
        max_workers=args.max_workers,
        explain_route=args.explain_route,
        progress_callback=progress_callback,
    )
    print(f"Job state: {state_file}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.verbose:
        config.logging.level = "DEBUG"
    _print_startup_check(config)

    pipeline = IngestionPipeline(config)
    progress_callback = _build_progress_printer()
    print("Processing progress:")
    state_file = pipeline.resume(
        state_path=args.job_state,
        max_workers=args.max_workers,
        explain_route=args.explain_route,
        progress_callback=progress_callback,
    )
    print(f"Resumed job state: {state_file}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    report = verify_output_tree(args.output)
    print(
        f"Verification report for {report.root}: total={report.total} ok={report.ok} flagged={report.flagged} failed={report.failed}"
    )
    if report.issues:
        for issue in report.issues:
            print(f"- {issue}")
    return 1 if report.failed else 0


def cmd_check_llm(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    client = LMStudioClient(config.llm)
    ok, detail = client.check_server()
    if ok:
        print(f"LM Studio reachable: {detail}")
        models = client.list_models()
        if models:
            print("Models:")
            for model in models:
                marker = "*" if model in {config.llm.primary_model, config.llm.fallback_model} else "-"
                print(f"{marker} {model}")
        return 0
    print(f"LM Studio check failed: {detail}")
    return 1


def cmd_init_config(args: argparse.Namespace) -> int:
    write_sample_config(args.path)
    print(f"Sample config written to {args.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "ingest":
            return cmd_ingest(args)
        if args.command == "resume":
            return cmd_resume(args)
        if args.command == "verify":
            return cmd_verify(args)
        if args.command == "check-llm":
            return cmd_check_llm(args)
        if args.command == "init-config":
            return cmd_init_config(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
