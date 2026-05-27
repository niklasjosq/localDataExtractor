from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import os
import tomllib


LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1"}

ENV_TOKEN_VAR = "LDX_LMSTUDIO_API_TOKEN"

_LAST_DOTENV_LOADED: Path | None = None


def last_dotenv_loaded() -> Path | None:
    """Return the .env path picked up by the most recent load_config(),
    or None if no .env file was discovered."""
    return _LAST_DOTENV_LOADED


def _load_dotenv(dotenv_path: Path) -> None:
    """Minimal .env reader: KEY=VALUE per line, # comments, optional
    surrounding quotes. Existing os.environ entries take precedence."""
    if not dotenv_path.is_file():
        return
    try:
        for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in {'"', "'"}
            ):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


def _find_project_root() -> Path | None:
    """Walk up from this source file looking for a pyproject.toml or
    .git marker. Reliable on editable installs, returns None when
    installed into site-packages."""
    start = Path(__file__).resolve()
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
        if (parent / ".git").exists():
            return parent
    return None


def _find_dotenv(config_path: Path | None) -> Path | None:
    explicit = os.environ.get("LDX_DOTENV", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate

    candidates: list[Path] = [Path.cwd() / ".env"]
    if config_path:
        candidates.append(config_path.parent / ".env")
    project_root = _find_project_root()
    if project_root is not None:
        candidates.append(project_root / ".env")
    candidates.append(
        Path.home() / ".config" / "localdataextractor" / ".env"
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@dataclass(slots=True)
class LLMConfig:
    base_url: str = "http://127.0.0.1:1234/v1"
    primary_model: str = "glm-ocr"
    fallback_model: str = "glm-ocr"
    timeout_seconds: int = 120
    retries: int = 2
    temperature: float = 0.1
    enable_vlm_repair: bool = True
    api_token: str = field(default="", repr=False)


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
    force_when_garbled: bool = True


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
    extraction_mode: str = "standard"


@dataclass(slots=True)
class TikaConfig:
    enabled: bool = False
    tika_jar_path: str = ""


@dataclass(slots=True)
class GLMOCRConfig:
    enabled: bool = True
    model_name: str = "glm-ocr"
    page_dpi: int = 300
    max_pages: int = 50
    timeout_seconds: int = 180
    use_pypdfium2: bool = True
    temperature_override: float = 0.0
    table_retry_enabled: bool = True
    table_retry_dpi: int = 400


@dataclass(slots=True)
class ImagePreprocessConfig:
    enabled: bool = True
    grayscale: bool = True
    deskew: bool = True
    denoise: bool = True
    binarize: bool = True
    binarize_method: str = "sauvola"  # sauvola | otsu | none
    margin_trim: bool = True
    target_long_edge: int = 2400


@dataclass(slots=True)
class TableExtractionConfig:
    pdfplumber_lines: bool = True
    pdfplumber_text: bool = True
    pdfplumber_lines_strict: bool = True
    camelot_lattice: bool = True
    camelot_stream: bool = True
    bbox_overlap_threshold: float = 0.5
    min_table_score: float = 40.0


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
    table_extraction: TableExtractionConfig = field(
        default_factory=TableExtractionConfig
    )
    image_preprocess: ImagePreprocessConfig = field(
        default_factory=ImagePreprocessConfig
    )
    render: RenderConfig = field(default_factory=RenderConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    tika: TikaConfig = field(default_factory=TikaConfig)
    glm_ocr: GLMOCRConfig = field(default_factory=GLMOCRConfig)
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
        "table_extraction": asdict(TableExtractionConfig()),
        "image_preprocess": asdict(ImagePreprocessConfig()),
        "render": asdict(RenderConfig()),
        "routing": asdict(RoutingConfig()),
        "tika": asdict(TikaConfig()),
        "glm_ocr": asdict(GLMOCRConfig()),
        "logging": asdict(LoggingConfig()),
    }


def load_config(config_path: str | Path | None = None) -> AppConfig:
    data = _defaults_dict()
    resolved_path: Path | None = None
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        with path.open("rb") as f:
            user_data = tomllib.load(f)
        data = _merge_dict(data, user_data)
        resolved_path = path

    global _LAST_DOTENV_LOADED
    dotenv_path = _find_dotenv(resolved_path)
    _LAST_DOTENV_LOADED = dotenv_path
    if dotenv_path is not None:
        _load_dotenv(dotenv_path)

    config = AppConfig(
        llm=LLMConfig(**data.get("llm", {})),
        retry=RetryConfig(**data.get("retry", {})),
        processing=ProcessingConfig(**data.get("processing", {})),
        ocr=OCRConfig(**data.get("ocr", {})),
        tables=TableConfig(**data.get("tables", {})),
        table_extraction=TableExtractionConfig(
            **data.get("table_extraction", {})
        ),
        image_preprocess=ImagePreprocessConfig(
            **data.get("image_preprocess", {})
        ),
        render=RenderConfig(**data.get("render", {})),
        routing=RoutingConfig(**data.get("routing", {})),
        tika=TikaConfig(**data.get("tika", {})),
        glm_ocr=GLMOCRConfig(**data.get("glm_ocr", {})),
        logging=LoggingConfig(**data.get("logging", {})),
    )
    if not config.llm.api_token:
        env_token = os.environ.get(ENV_TOKEN_VAR, "").strip()
        if env_token:
            config.llm.api_token = env_token
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
    valid_modes = {"standard", "glm_ocr", "highest_accuracy"}
    if config.routing.extraction_mode not in valid_modes:
        raise ConfigError(
            f"routing.extraction_mode must be one of {valid_modes}"
        )
    if config.glm_ocr.page_dpi < 72:
        raise ConfigError("glm_ocr.page_dpi must be >= 72")
    if config.glm_ocr.max_pages < 1:
        raise ConfigError("glm_ocr.max_pages must be >= 1")
    if config.glm_ocr.table_retry_dpi < 72:
        raise ConfigError("glm_ocr.table_retry_dpi must be >= 72")
    if config.image_preprocess.binarize_method not in {
        "sauvola", "otsu", "none",
    }:
        raise ConfigError(
            "image_preprocess.binarize_method must be one of "
            "sauvola | otsu | none"
        )
    if config.image_preprocess.target_long_edge < 256:
        raise ConfigError(
            "image_preprocess.target_long_edge must be >= 256"
        )
    if not (
        0.0 <= config.table_extraction.bbox_overlap_threshold <= 1.0
    ):
        raise ConfigError(
            "table_extraction.bbox_overlap_threshold must be in [0, 1]"
        )


def write_sample_config(path: str | Path) -> None:
    sample = (
        "# localdataextractor sample config\n"
        "[llm]\n"
        'base_url = "http://127.0.0.1:1234/v1"\n'
        'primary_model = "glm-ocr"\n'
        'fallback_model = "glm-ocr"\n'
        "timeout_seconds = 120\n"
        "retries = 2\n"
        "temperature = 0.1\n"
        "enable_vlm_repair = true\n"
        '# Set if your LM Studio server requires an API key:\n'
        'api_token = ""\n\n'
        "[retry]\n"
        "confidence_threshold = 95.0\n"
        "max_route_attempts = 5\n"
        "table_repair_attempts = 2\n"
        "retry_backoff_seconds = 1.0\n\n"
        "[processing]\n"
        "max_workers = 2\n"
        'include_globs = ["*", "**/*"]\n'
        'exclude_globs = ["**/.DS_Store", "**/~$*"]\n\n'
        "[ocr]\n"
        "enabled = true\n"
        "dpi = 300\n"
        "deskew = true\n"
        "clean = true\n"
        "optimize = 0\n"
        'language = "eng"\n'
        "force_when_garbled = true\n\n"
        "[tables]\n"
        "high_effort = true\n"
        "important_row_min = 2\n"
        "strict_column_consistency = true\n"
        "max_empty_ratio = 0.4\n"
        "max_duplicate_row_ratio = 0.15\n\n"
        "[table_extraction]\n"
        "pdfplumber_lines = true\n"
        "pdfplumber_text = true\n"
        "pdfplumber_lines_strict = true\n"
        "camelot_lattice = true\n"
        "camelot_stream = true\n"
        "bbox_overlap_threshold = 0.5\n"
        "min_table_score = 40.0\n\n"
        "[image_preprocess]\n"
        "enabled = true\n"
        "grayscale = true\n"
        "deskew = true\n"
        "denoise = true\n"
        "binarize = true\n"
        'binarize_method = "sauvola"\n'
        "margin_trim = true\n"
        "target_long_edge = 2400\n\n"
        "[render]\n"
        "image_dpi = 220\n"
        "markdown_table_fallback = true\n\n"
        "[routing]\n"
        'fallback_order = ["markitdown", "docling", "ocr_docling", "tika"]\n'
        "min_characters_for_good_extraction = 300\n"
        'extraction_mode = "standard"  '
        "# standard | glm_ocr | highest_accuracy\n\n"
        "[glm_ocr]\n"
        "enabled = true\n"
        'model_name = "glm-ocr"\n'
        "page_dpi = 300\n"
        "max_pages = 50\n"
        "timeout_seconds = 180\n"
        "use_pypdfium2 = true\n"
        "temperature_override = 0.0\n"
        "table_retry_enabled = true\n"
        "table_retry_dpi = 400\n\n"
        "[tika]\n"
        "enabled = false\n"
        'tika_jar_path = ""\n\n'
        "[logging]\n"
        'level = "INFO"\n'
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sample, encoding="utf-8")
