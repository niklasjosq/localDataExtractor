from __future__ import annotations

import logging
from pathlib import Path


def setup_console_logger(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("localdataextractor")
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
        )
        logger.addHandler(handler)
    return logger


def build_file_logger(log_path: Path, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(f"localdataextractor.file.{log_path.stem}")
    logger.setLevel(level.upper())
    logger.propagate = False
    logger.handlers.clear()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    )
    logger.addHandler(handler)
    return logger
