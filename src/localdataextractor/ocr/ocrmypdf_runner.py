from __future__ import annotations

from pathlib import Path
import subprocess

from localdataextractor.config import OCRConfig


def run_ocrmypdf(
    input_pdf: Path,
    output_pdf: Path,
    config: OCRConfig,
    force: bool = False,
) -> tuple[bool, str]:
    cmd = [
        "ocrmypdf",
        "--force-ocr" if force else "--skip-text",
        "--output-type",
        "pdf",
        "--jobs",
        "1",
        "--optimize",
        str(config.optimize),
        "--tesseract-timeout",
        "120",
        "--language",
        config.language,
    ]
    if config.deskew:
        cmd.append("--deskew")
    if config.clean:
        cmd.append("--clean")
    cmd.extend([str(input_pdf), str(output_pdf)])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    message = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode == 0, message
