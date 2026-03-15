from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import urlparse

import requests

from localdataextractor.config.settings import LLMConfig, LOCALHOST_HOSTS
from localdataextractor.models import TableBlock


@dataclass(slots=True)
class LLMResponse:
    ok: bool
    model: str
    content: dict[str, Any]
    error: str = ""


class LMStudioClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._validate_localhost(config.base_url)

    @staticmethod
    def _validate_localhost(base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.hostname not in LOCALHOST_HOSTS:
            raise ValueError("LM Studio base URL must be localhost only")

    def check_server(self) -> tuple[bool, str]:
        try:
            resp = requests.get(
                f"{self.config.base_url.rstrip('/')}/models",
                timeout=min(10, self.config.timeout_seconds),
            )
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            model_ids = [item.get("id", "") for item in data.get("data", [])]
            summary = ", ".join([m for m in model_ids if m][:6])
            if not summary:
                summary = "server reachable; no models listed"
            return True, summary
        except Exception as exc:
            return False, str(exc)

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(
                f"{self.config.base_url.rstrip('/')}/models",
                timeout=min(15, self.config.timeout_seconds),
            )
            resp.raise_for_status()
            data = resp.json()
            return [item.get("id", "") for item in data.get("data", []) if item.get("id")]
        except Exception:
            return []

    def _chat_json(self, model: str, system_prompt: str, user_prompt: str) -> LLMResponse:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = requests.post(
                f"{self.config.base_url.rstrip('/')}/chat/completions",
                json=payload,
                timeout=self.config.timeout_seconds,
            )
            if resp.status_code != 200:
                return LLMResponse(False, model, {}, f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return LLMResponse(True, model, parsed)
        except Exception as exc:
            return LLMResponse(False, model, {}, str(exc))

    def request_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        models_to_try = [self.config.primary_model, self.config.fallback_model]
        for model in models_to_try:
            for _ in range(self.config.retries + 1):
                response = self._chat_json(model, system_prompt, user_prompt)
                if response.ok:
                    return response
        return LLMResponse(False, models_to_try[-1], {}, "all model attempts failed")

    def repair_table(self, table: TableBlock) -> tuple[TableBlock, str | None]:
        if not self.config.enable_vlm_repair:
            return table, None

        system_prompt = (
            "You normalize extracted document tables. "
            "Return JSON with keys: header_rows (list of rows), body_rows (list of rows), "
            "caption (string|null), notes (list). Keep semantics, do not invent data."
        )
        user_prompt = json.dumps(
            {
                "table_id": table.table_id,
                "caption": table.caption,
                "header_rows": table.header_rows,
                "body_rows": table.body_rows,
                "column_count": table.column_count,
                "row_count": table.row_count,
            },
            ensure_ascii=False,
        )
        response = self.request_json(system_prompt, user_prompt)
        if not response.ok:
            return table, response.error

        payload = response.content
        headers = payload.get("header_rows") or table.header_rows
        body = payload.get("body_rows") or table.body_rows
        caption = payload.get("caption", table.caption)
        table.header_rows = [[str(cell) for cell in row] for row in headers]
        table.body_rows = [[str(cell) for cell in row] for row in body]
        table.caption = str(caption) if caption is not None else None
        table.column_count = max([len(r) for r in table.header_rows + table.body_rows], default=0)
        table.row_count = len(table.body_rows)
        return table, None
