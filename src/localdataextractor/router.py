from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from localdataextractor.config import AppConfig
from localdataextractor.models import RouteDecision


@dataclass(slots=True)
class FileInfo:
    path: Path
    extension: str
    size: int


def get_file_info(path: Path) -> FileInfo:
    return FileInfo(path=path, extension=path.suffix.lower(), size=path.stat().st_size)


_GLM_OCR_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
}


def plan_routes(
    file_info: FileInfo, config: AppConfig,
) -> list[RouteDecision]:
    mode = config.routing.extraction_mode

    if mode == "highest_accuracy":
        return _plan_highest_accuracy(file_info, config)
    if mode == "glm_ocr":
        return _plan_glm_ocr_primary(file_info, config)
    return _plan_standard(file_info, config)


def _plan_standard(
    file_info: FileInfo, config: AppConfig,
) -> list[RouteDecision]:
    ext = file_info.extension
    routes: list[RouteDecision] = []

    if ext in {".txt", ".css"}:
        routes.append(
            RouteDecision(
                route_id="direct_text",
                parser="text",
                reason="Deterministic direct read is best for plain text-like files.",
            )
        )
        return routes

    if ext == ".pdf":
        routes.append(
            RouteDecision(
                route_id="pdf_docling",
                parser="docling",
                reason="PDF route prefers Docling for layout-aware extraction.",
            )
        )
        routes.append(
            RouteDecision(
                route_id="pdf_ocr_docling",
                parser="ocr_docling",
                reason="OCR-assisted retry for scanned/image-heavy PDFs.",
            )
        )
        routes.append(
            RouteDecision(
                route_id="pdf_tika",
                parser="tika",
                reason="Local Apache Tika fallback for difficult PDFs.",
            )
        )
        return _filter_tika(routes, config)

    if ext in {".docx", ".pptx", ".xlsx", ".xls"}:
        routes.append(
            RouteDecision(
                route_id="office_markitdown",
                parser="markitdown",
                reason="Office route prefers MarkItDown conversion first.",
            )
        )
        routes.append(
            RouteDecision(
                route_id="office_docling",
                parser="docling",
                reason="Docling fallback when Office extraction is weak.",
            )
        )
        routes.append(
            RouteDecision(
                route_id="office_tika",
                parser="tika",
                reason="Tika fallback for difficult Office files.",
            )
        )
        return _filter_tika(routes, config)

    if ext in {".doc", ".ppt"}:
        routes.append(
            RouteDecision(
                route_id="legacy_libreoffice_markitdown",
                parser="libreoffice_markitdown",
                reason="Legacy Office formats are converted with LibreOffice first.",
            )
        )
        routes.append(
            RouteDecision(
                route_id="legacy_libreoffice_docling",
                parser="libreoffice_docling",
                reason="Converted fallback via Docling after LibreOffice export.",
            )
        )
        routes.append(
            RouteDecision(
                route_id="legacy_tika",
                parser="tika",
                reason="Tika fallback for legacy Office files.",
            )
        )
        return _filter_tika(routes, config)

    return [
        RouteDecision(
            route_id="tika_only",
            parser="tika",
            reason="Unknown type fallback route.",
        )
    ]


def _plan_glm_ocr_primary(
    file_info: FileInfo, config: AppConfig,
) -> list[RouteDecision]:
    routes: list[RouteDecision] = []
    ext = file_info.extension

    if ext in _GLM_OCR_EXTENSIONS:
        routes.append(RouteDecision(
            route_id="glm_ocr_primary",
            parser="glm_ocr",
            reason="GLM-OCR vision model for high-accuracy extraction.",
        ))

    routes.extend(_plan_standard(file_info, config))
    return routes


def _plan_highest_accuracy(
    file_info: FileInfo, config: AppConfig,
) -> list[RouteDecision]:
    routes = _plan_standard(file_info, config)
    ext = file_info.extension

    if ext in _GLM_OCR_EXTENSIONS:
        routes.append(RouteDecision(
            route_id="accuracy_glm_ocr",
            parser="glm_ocr",
            reason="GLM-OCR added for highest-accuracy comparison.",
        ))

    return routes


def _filter_tika(routes: list[RouteDecision], config: AppConfig) -> list[RouteDecision]:
    if config.tika.enabled:
        return routes
    return [route for route in routes if route.parser != "tika"]


def explain_routes(routes: list[RouteDecision]) -> str:
    lines = ["Route plan:"]
    for index, route in enumerate(routes, start=1):
        detail = f" ({route.detail})" if route.detail else ""
        lines.append(f"{index}. {route.route_id} -> {route.parser}: {route.reason}{detail}")
    return "\n".join(lines)
