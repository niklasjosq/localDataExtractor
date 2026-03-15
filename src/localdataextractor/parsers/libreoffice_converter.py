from __future__ import annotations

from pathlib import Path
import subprocess


def convert_with_libreoffice(input_path: Path, output_dir: Path) -> tuple[Path | None, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = input_path.suffix.lower()
    if ext == ".doc":
        target_ext = "docx"
    elif ext == ".ppt":
        target_ext = "pptx"
    else:
        target_ext = "pdf"

    cmd = [
        "soffice",
        "--headless",
        "--convert-to",
        target_ext,
        "--outdir",
        str(output_dir),
        str(input_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    message = (proc.stdout + "\n" + proc.stderr).strip()
    if proc.returncode != 0:
        return None, message

    converted = output_dir / f"{input_path.stem}.{target_ext}"
    if not converted.exists():
        return None, f"Converted file missing: {converted}\n{message}"
    return converted, message
