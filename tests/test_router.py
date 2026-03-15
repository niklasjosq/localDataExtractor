from __future__ import annotations

from pathlib import Path

from localdataextractor.config import load_config
from localdataextractor.router import FileInfo, explain_routes, plan_routes


def _file_info(path: str, ext: str) -> FileInfo:
    return FileInfo(path=Path(path), extension=ext, size=100)


def test_routes_for_text() -> None:
    config = load_config(None)
    routes = plan_routes(_file_info("a.txt", ".txt"), config)
    assert len(routes) == 1
    assert routes[0].parser == "text"


def test_routes_for_pdf_without_tika() -> None:
    config = load_config(None)
    config.tika.enabled = False
    routes = plan_routes(_file_info("a.pdf", ".pdf"), config)
    assert [r.parser for r in routes] == ["docling", "ocr_docling"]


def test_routes_for_legacy_doc() -> None:
    config = load_config(None)
    routes = plan_routes(_file_info("a.doc", ".doc"), config)
    assert routes[0].parser == "libreoffice_markitdown"
    assert "LibreOffice" in routes[0].reason


def test_explain_routes_contains_route_ids() -> None:
    config = load_config(None)
    routes = plan_routes(_file_info("a.pdf", ".pdf"), config)
    text = explain_routes(routes)
    assert "Route plan" in text
    assert routes[0].route_id in text
