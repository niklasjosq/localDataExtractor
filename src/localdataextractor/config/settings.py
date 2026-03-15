from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import tomllib


LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(slots=True)
class LLMConfig:
    base_url: str = "http://localhost:1234/v1"
    primary_model: str = "qwen3-vl-8b"
    fallback_model: str = "qwen2.5-vl-7b"
    timeout_seconds: int = 120
    retries: int = 2
    temperature: float = 0.1
    enable_vlm_repair: bool = True


@dataclass(slots=True)
class RetryConfig:
    confidence_threshold: float = 95.0
    max_route_attempts: int = 5
    table_repair_attempts: int = 2
    retry_backoff_seconds: float = 1.0


@dataclass(slots=True)
class ProcessingConfig:
    max_workers: int = 2
    include_globs: list[str] = field(default_factory=lambda: ["*", "**/*"])
    exclude_globs: list[str] = field(default_factory=lambda: ["**/.DS_Store", "**/~$*"])


@dataclass(slots=True)
class OCRConfig:
    enabled: bool = True
    dpi: int = 300
    deskew: bool = True
    clean: bool = True
    optimize: int = 0
    language: str = "eng"


@dataclass(slots=True)
class TableConfig:
    high_effort: bool = True
    important_row_min: int = 2
    strict_column_consistency: bool = True
    max_empty_ratio: float = 0.4
    max_duplicate_row_ratio: float = 0.15


@dataclass(slots=True)
class RenderConfig:
    image_dpi: int = 220
    markdown_table_fallback: bool = True


@dataclass(slots=True)
class RoutingConfig:
    fallback_order: list[str] = field(
        default_factory=lambda: ["markitdown", "docling", "ocr_docling", "tika"]
    )
    min_characters_for_good_extraction: int = 300


@dataclass(slots=True)
class TikaConfig:
    enabled: bool = False
    tika_jar_path: str = ""


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(slots=True)
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    tables: TableConfig = field(default_factory=TableConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    tika: TikaConfig = field(default_factory=TikaConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


class ConfigError(RuntimeError):
    pass


def _merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _defaults_dict() -> dict[str, Any]:
    return {
        "llm": asdict(LLMConfig()),
        "retry": asdict(RetryConfig()),
        "processing": asdict(ProcessingConfig()),
        "ocr": asdict(OCRConfig()),
        "tables": asdict(TableConfig()),
        "render": asdict(RenderConfig()),
        "routing": asdict(RoutingConfig()),
        "tika": asdict(TikaConfig()),
        "logging": asdict(LoggingConfig()),
    }


def load_config(config_path: str | Path | None = None) -> AppConfig:
    data = _defaults_dict()
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        with path.open("rb") as f:
            user_data = tomllib.load(f)
        data = _merge_dict(data, user_data)

    config = AppConfig(
        llm=LLMConfig(**data.get("llm", {})),
        retry=RetryConfig(**data.get("retry", {})),
        processing=ProcessingConfig(**data.get("processing", {})),
        ocr=OCRConfig(**data.get("ocr", {})),
        tables=TableConfig(**data.get("tables", {})),
        render=RenderConfig(**data.get("render", {})),
        routing=RoutingConfig(**data.get("routing", {})),
        tika=TikaConfig(**data.get("tika", {})),
        logging=LoggingConfig(**data.get("logging", {})),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    parsed = urlparse(config.llm.base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError("llm.base_url must be http/https")
    if parsed.hostname not in LOCALHOST_HOSTS:
        raise ConfigError("llm.base_url must target localhost only")
    if config.retry.confidence_threshold < 0 or config.retry.confidence_threshold > 100:
        raise ConfigError("retry.confidence_threshold must be in [0, 100]")
    if config.processing.max_workers < 1:
        raise ConfigError("processing.max_workers must be >= 1")
    if config.ocr.dpi < 72:
        raise ConfigError("ocr.dpi must be >= 72")
    if config.retry.max_route_attempts < 1:
        raise ConfigError("retry.max_route_attempts must be >= 1")


def write_sample_config(path: str | Path) -> None:
    sample = """# localdataextractor sample config\n[llm]\nbase_url = \"http://localhost:1234/v1\"\nprimary_model = \"qwen3-vl-8b\"\nfallback_model = \"qwen2.5-vl-7b\"\ntimeout_seconds = 120\nretries = 2\ntemperature = 0.1\nenable_vlm_repair = true\n\n[retry]\nconfidence_threshold = 95.0\nmax_route_attempts = 5\ntable_repair_attempts = 2\nretry_backoff_seconds = 1.0\n\n[processing]\nmax_workers = 2\ninclude_globs = [\"*\", \"**/*\"]\nexclude_globs = [\"**/.DS_Store\", \"**/~$*\"]\n\n[ocr]\nenabled = true\ndpi = 300\ndeskew = true\nclean = true\noptimize = 0\nlanguage = \"eng\"\n\n[tables]\nhigh_effort = true\nimportant_row_min = 2\nstrict_column_consistency = true\nmax_empty_ratio = 0.4\nmax_duplicate_row_ratio = 0.15\n\n[render]\nimage_dpi = 220\nmarkdown_table_fallback = true\n\n[routing]\nfallback_order = [\"markitdown\", \"docling\", \"ocr_docling\", \"tika\"]\nmin_characters_for_good_extraction = 300\n\n[tika]\nenabled = false\ntika_jar_path = \"\"\n\n[logging]\nlevel = \"INFO\"\n"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sample, encoding="utf-8")
