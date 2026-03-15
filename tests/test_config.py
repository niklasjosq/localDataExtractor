from __future__ import annotations

from pathlib import Path

import pytest

from localdataextractor.config import ConfigError, load_config
from localdataextractor.llm.client import LMStudioClient


def test_load_default_config() -> None:
    config = load_config(None)
    assert config.retry.confidence_threshold == 95.0
    assert config.processing.max_workers == 2
    assert config.llm.base_url.startswith("http://localhost")


def test_reject_non_localhost(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text('[llm]\nbase_url = "http://example.com:1234/v1"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_llm_client_localhost_guard() -> None:
    with pytest.raises(ValueError):
        LMStudioClient(type("Cfg", (), {"base_url": "http://remote-host:1234/v1", "primary_model": "a", "fallback_model": "b", "timeout_seconds": 10, "retries": 0, "temperature": 0.1, "enable_vlm_repair": True})())
