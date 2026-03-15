from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import which
import subprocess
from typing import Literal

from localdataextractor.config import AppConfig
from localdataextractor.llm.client import LMStudioClient


@dataclass(slots=True)
class DependencyStatus:
    name: str
    available: bool
    required: bool
    detail: str


@dataclass(slots=True)
class StartupValidationResult:
    statuses: list[DependencyStatus]

    @property
    def ok(self) -> bool:
        return all(item.available or not item.required for item in self.statuses)


JAVA_STUB_MESSAGES = (
    "Unable to locate a Java Runtime",
    "No Java runtime present",
)


def _check_command(name: str) -> tuple[bool, str]:
    path = which(name)
    if not path:
        return False, "not found in PATH"
    return True, path


def _check_java_runtime() -> tuple[bool, str]:
    java_path = which("java")
    if not java_path:
        return False, "java executable not found"
    proc = subprocess.run(
        ["java", "-version"],
        capture_output=True,
        text=True,
        check=False,
    )
    msg = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0 and any(fragment in msg for fragment in JAVA_STUB_MESSAGES):
        return False, msg.splitlines()[0] if msg else "java runtime unavailable"
    return True, java_path


def run_startup_validation(config: AppConfig) -> StartupValidationResult:
    statuses: list[DependencyStatus] = []

    soffice_ok, soffice_detail = _check_command("soffice")
    statuses.append(
        DependencyStatus(
            name="LibreOffice (soffice)",
            available=soffice_ok,
            required=False,
            detail=soffice_detail,
        )
    )

    tess_ok, tess_detail = _check_command("tesseract")
    statuses.append(
        DependencyStatus(
            name="Tesseract",
            available=tess_ok,
            required=config.ocr.enabled,
            detail=tess_detail,
        )
    )

    ocrmypdf_ok, ocrmypdf_detail = _check_command("ocrmypdf")
    statuses.append(
        DependencyStatus(
            name="OCRmyPDF",
            available=ocrmypdf_ok,
            required=False,
            detail=ocrmypdf_detail,
        )
    )

    java_ok, java_detail = _check_java_runtime()
    statuses.append(
        DependencyStatus(
            name="Java Runtime",
            available=java_ok,
            required=bool(config.tika.enabled),
            detail=java_detail,
        )
    )

    if config.tika.enabled:
        jar_path = Path(config.tika.tika_jar_path)
        statuses.append(
            DependencyStatus(
                name="Apache Tika JAR",
                available=jar_path.exists() and jar_path.is_file(),
                required=True,
                detail=str(jar_path),
            )
        )

    llm_client = LMStudioClient(config.llm)
    llm_ok, llm_detail = llm_client.check_server()
    statuses.append(
        DependencyStatus(
            name="LM Studio",
            available=llm_ok,
            required=False,
            detail=llm_detail,
        )
    )

    return StartupValidationResult(statuses=statuses)
