"""Thin chat client wrapper around Ollama /api/chat.

The previous implementation used `format: schema.model_json_schema()` and a
fixed num_predict budget of 350, which was both too small for structured
AnswerDraft payloads and too strict for the qwen3.5 chat model. This client
keeps the JSON schema but exposes a per-call budget and treats parse
failures as recoverable for one round only.

The client does not retry internally; the service decides when a retry is
appropriate (e.g. one revision pass for an audited draft).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


class ChatError(Exception):
    """Wrapper around transport / parse failures."""

    def __init__(self, stage: str, exc: Exception) -> None:
        super().__init__(f"{stage}: {type(exc).__name__}: {exc}")
        self.stage = stage
        self.exc = exc


class ChatClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "qwen3.5:9b-q4_K_M",
                 timeout: float = 240.0,
                 num_ctx: int = 8192,
                 keep_alive: str = "10m") -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive

    def chat(self, system: str, user_payload: dict[str, Any],
             json_schema: dict[str, Any],
             num_predict: int = 1200,
             temperature: float = 0.0) -> dict[str, Any]:
        """Send one chat turn and return the parsed JSON object."""
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "format": json_schema,
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": self.num_ctx,
                "num_predict": num_predict,
            },
        }
        try:
            with httpx.Client(trust_env=False, timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}/api/chat", json=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ChatError("transport", exc) from exc
        try:
            content = payload["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ChatError("response_shape", exc) from exc
        text = self._strip_think(content)
        try:
            return json.loads(text)
        except (ValueError, TypeError) as exc:
            raise ChatError("parse", ValueError(f"content was: {text[:240]!r}")) from exc

    @staticmethod
    def _strip_think(content: str) -> str:
        """qwen3.5 may emit <think>...</think> even with think=False. Strip it
        before JSON parsing to avoid the leading artifact breaking it."""
        if not content:
            return content
        if "<think>" in content and "</think>" in content:
            try:
                end = content.index("</think>") + len("</think>")
                content = content[end:]
            except ValueError:
                content = content.split("<think>", 1)[-1]
        return content.strip()
