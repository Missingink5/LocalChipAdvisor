"""Thin chat client wrapper around Ollama /api/chat.

The previous implementation used `format: schema.model_json_schema()` and a
fixed num_predict budget of 350, which was both too small for structured
AnswerDraft payloads and too strict for the qwen3.5 chat model. This client
keeps the JSON schema but exposes a per-call budget and treats parse
failures as recoverable for one round only.

The client does not retry internally; the service decides when a retry is
appropriate (e.g. one revision pass for an audited draft).

Every chat call reports Ollama /api/chat timing fields (load_duration,
prompt_eval_*, eval_*) as one metrics dict. Metrics belong to a single
request: they are emitted through the optional per-call `metrics_sink` (or
LOGGER.info when no sink is given) and are never stored on the client, so a
service shared across Streamlit sessions cannot leak one request's
diagnostics into another.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


def _seconds(nanoseconds: Any) -> float | None:
    """Convert an Ollama ns duration to seconds (float), None when absent."""
    if nanoseconds is None:
        return None
    try:
        return round(int(nanoseconds) / 1_000_000_000, 4)
    except (TypeError, ValueError):
        return None


def _tok_per_s(count: Any, duration_ns: Any) -> float | None:
    seconds = _seconds(duration_ns)
    if seconds is None or not seconds or count is None:
        return None
    try:
        return round(int(count) / seconds, 1)
    except (TypeError, ValueError):
        return None


def make_chat_metrics(payload: dict[str, Any], *, stage: str, model: str,
                      wall_seconds: float, num_ctx: int, num_predict: int,
                      temperature: float) -> dict[str, Any]:
    """Extract per-stage Ollama metrics from one /api/chat response."""
    return {
        "stage": stage,
        "model": model,
        "wall_seconds": round(wall_seconds, 4),
        "ollama_total_seconds": _seconds(payload.get("total_duration")),
        "load_seconds": _seconds(payload.get("load_duration")),
        "prompt_tokens": payload.get("prompt_eval_count"),
        "prompt_eval_seconds": _seconds(payload.get("prompt_eval_duration")),
        "prompt_tokens_per_second": _tok_per_s(
            payload.get("prompt_eval_count"), payload.get("prompt_eval_duration")),
        "output_tokens": payload.get("eval_count"),
        "eval_seconds": _seconds(payload.get("eval_duration")),
        "output_tokens_per_second": _tok_per_s(
            payload.get("eval_count"), payload.get("eval_duration")),
        "done_reason": payload.get("done_reason"),
        "num_ctx": num_ctx,
        "num_predict": num_predict,
        "temperature": temperature,
    }


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
        # Persistent HTTP connection: Ollama is local, the URL never
        # changes, and every chat round currently opens a fresh
        # httpx.Client (TCP/TLS handshake on each call). One client
        # lifetime avoids that and matches how the Index already keeps
        # an httpx.Client on self.
        self._http = httpx.Client(base_url=self.base_url, timeout=self.timeout,
                                  trust_env=False)
        self._owns_http = True

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def chat(self, system: str, user_payload: dict[str, Any],
             json_schema: dict[str, Any],
             num_predict: int = 1200,
             temperature: float = 0.0,
             stage: str = "chat",
             metrics_sink: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        """Send one chat turn and return the parsed JSON object.

        `stage` and `metrics_sink` are diagnostics-only: they label which
        pipeline stage this call belongs to (intent / generation / audit /
        revision / revision_audit) and receive the per-request metrics dict.
        No metrics are kept on the client; with no sink they are logged.
        """
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
        started = time.perf_counter()
        try:
            response = self._http.post("/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            wall = round(time.perf_counter() - started, 4)
            LOGGER.warning("chat %s failed after %.1fs: %s", stage, wall, exc)
            raise ChatError("transport", exc) from exc
        metrics = make_chat_metrics(
            payload, stage=stage, model=self.model,
            wall_seconds=round(time.perf_counter() - started, 4),
            num_ctx=self.num_ctx, num_predict=num_predict, temperature=temperature)
        if metrics_sink is not None:
            metrics_sink(metrics)
        else:
            LOGGER.info(
                "ollama stage=%s model=%s wall=%.1fs load=%.1fs "
                "prompt=%s tokens (%.0f tok/s) output=%s tokens (%.0f tok/s)",
                metrics["stage"], metrics["model"], metrics["wall_seconds"] or 0.0,
                metrics["load_seconds"] or 0.0,
                metrics["prompt_tokens"], metrics["prompt_tokens_per_second"] or 0.0,
                metrics["output_tokens"], metrics["output_tokens_per_second"] or 0.0,
            )
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
