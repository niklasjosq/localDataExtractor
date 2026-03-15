from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import uuid

from localdataextractor.models import (
    ConfidenceReport,
    ExtractionAttempt,
    FileState,
    JobState,
    dataclass_to_dict,
)
from localdataextractor.utils.json_io import read_json, write_json


SCHEMA_VERSION = "1.0"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStateStore:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def create(self, input_root: Path, output_root: Path, files: list[Path]) -> JobState:
        input_resolved = input_root.resolve()
        file_map: dict[str, FileState] = {}
        for file in files:
            relative = str(file.resolve().relative_to(input_resolved))
            file_map[relative] = FileState(
                source_path=str(file.resolve()),
                relative_path=relative,
            )

        now = _utc_now_iso()
        state = JobState(
            schema_version=SCHEMA_VERSION,
            job_id=str(uuid.uuid4()),
            input_root=str(input_resolved),
            output_root=str(output_root.resolve()),
            created_at=now,
            updated_at=now,
            files=file_map,
        )
        self.save(state)
        return state

    def load(self) -> JobState:
        payload = read_json(self.state_path)
        files: dict[str, FileState] = {}
        for key, value in payload.get("files", {}).items():
            attempts: list[ExtractionAttempt] = []
            for raw_attempt in value.get("attempts", []):
                conf = raw_attempt.get("confidence", {})
                attempts.append(
                    ExtractionAttempt(
                        timestamp=raw_attempt.get("timestamp", ""),
                        route=raw_attempt.get("route", ""),
                        parser=raw_attempt.get("parser", ""),
                        model=raw_attempt.get("model"),
                        confidence=ConfidenceReport(
                            overall=float(conf.get("overall", 0.0)),
                            block_scores=dict(conf.get("block_scores", {})),
                            table_scores=dict(conf.get("table_scores", {})),
                        ),
                        reasons_for_retry=list(raw_attempt.get("reasons_for_retry", [])),
                        warnings=list(raw_attempt.get("warnings", [])),
                        artifacts=dict(raw_attempt.get("artifacts", {})),
                    )
                )

            file_state = FileState(**{k: v for k, v in value.items() if k != "attempts"})
            file_state.attempts = attempts
            files[key] = file_state

        return JobState(
            schema_version=payload["schema_version"],
            job_id=payload["job_id"],
            input_root=payload["input_root"],
            output_root=payload["output_root"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            files=files,
        )

    def save(self, state: JobState) -> None:
        state.updated_at = _utc_now_iso()
        write_json(self.state_path, dataclass_to_dict(state))

    def update_file(self, state: JobState, relative_path: str, new_file_state: FileState) -> None:
        state.files[relative_path] = replace(new_file_state, updated_at=_utc_now_iso())
        self.save(state)
