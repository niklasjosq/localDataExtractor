from __future__ import annotations

from pathlib import Path

from localdataextractor.models import VerificationReport
from localdataextractor.utils.json_io import read_json


REQUIRED_JSON_KEYS = {
    "schema_version",
    "source",
    "extraction_attempts",
    "route_history",
    "overall_confidence",
    "below_threshold",
}


def verify_output_tree(root: Path) -> VerificationReport:
    issues: list[str] = []
    json_files = [p for p in root.rglob("*.json") if p.name != "job_state.json"]

    ok = 0
    flagged = 0
    failed = 0

    for json_file in json_files:
        rel = str(json_file.relative_to(root))
        stem = json_file.with_suffix("")
        md_file = stem.with_suffix(".md")
        log_file = stem.with_suffix(".log")

        local_issues: list[str] = []

        if not md_file.exists():
            local_issues.append("missing markdown output")
        if not log_file.exists():
            local_issues.append("missing log output")

        try:
            payload = read_json(json_file)
        except Exception as exc:
            local_issues.append(f"invalid json: {exc}")
            issues.append(f"{rel}: {', '.join(local_issues)}")
            failed += 1
            continue

        for key in REQUIRED_JSON_KEYS:
            if key not in payload:
                local_issues.append(f"missing key: {key}")

        if payload.get("overall_confidence") is None:
            local_issues.append("missing overall confidence")

        routes = payload.get("route_history", [])
        if not isinstance(routes, list) or not routes:
            local_issues.append("route history is empty")

        tables = payload.get("tables", [])
        if tables:
            try:
                md_content = md_file.read_text(encoding="utf-8")
            except Exception:
                md_content = ""
            if "|" not in md_content:
                local_issues.append("tables detected in JSON but markdown table representation missing")

        if payload.get("below_threshold"):
            flagged += 1

        if local_issues:
            issues.append(f"{rel}: {', '.join(local_issues)}")
            failed += 1
        else:
            ok += 1

    total = len(json_files)
    return VerificationReport(
        root=str(root),
        total=total,
        ok=ok,
        flagged=flagged,
        failed=failed,
        issues=issues,
    )
