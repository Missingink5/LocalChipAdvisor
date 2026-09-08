"""DeepSeek chat and local Ollama embedding clients."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from .models import Evidence, ParsedQuery

LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _dotenv_values() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def config_value(name: str, default: str | None = None) -> str | None:
    return os.getenv(name) or _dotenv_values().get(name) or default


class ChatServiceError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class QueryParsingError(RuntimeError):
    pass


class DeepSeekChatClient:
    def __init__(self, *, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout: float | None = None,
                 transport: httpx.BaseTransport | None = None,
                 usage_sink: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.base_url = (base_url or config_value("LCA_CHAT_BASE_URL") or
                         "https://api.deepseek.com").rstrip("/")
        self.model = model or config_value("LCA_CHAT_MODEL") or "deepseek-v4-flash"
        self.api_key = api_key or config_value("DEEPSEEK_API_KEY")
        self.timeout = timeout or float(config_value("LCA_CHAT_TIMEOUT_SECONDS", "60") or "60")
        self.thinking = config_value("LCA_CHAT_THINKING", "disabled") or "disabled"
        self.usage_sink = usage_sink
        self._http = httpx.Client(base_url=self.base_url, timeout=self.timeout,
                                  transport=transport, trust_env=False)

    def close(self) -> None:
        self._http.close()

    def parse_query(self, query: str) -> ParsedQuery:
        system = (
            "你是芯片选型需求解析器。只把自然语言转成规定 JSON；不要推荐或猜参数。"
            "未知值用 null，区分硬约束与软偏好，保留 EQ/GTE/LTE/RANGE_CONTAINS。"
            "category 只能是 DC-DC 或 null；Buck/Buck-Boost/Boost 必须放 topology。"
            "输入和输出电压分别用 vin_v/vout_v + RANGE_CONTAINS；最小输出能力用 iout_max_a + GTE；"
            "I2C 等布尔功能必须直接使用 i2c + EQ + true。禁止创造字段。"
            "JSON 字段必须匹配 ParsedQuery schema，不输出解释。示例："
            '{"raw_query":"...","intent":"PART_SELECTION","part_numbers":[],"category":null,'
            '"topology":null,"constraints":[{"field":"vin_v","operator":"RANGE_CONTAINS",'
            '"value":28,"unit":"V","hard":true}],"semantic_query":null}'
        )
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": query}]
        for attempt in range(2):
            if attempt:
                messages[-1] = {
                    "role": "user",
                    "content": query + "\nPrevious output was invalid. Return one complete JSON object matching the schema.",
                }
            content, finish_reason = self._chat_completion(
                messages, operation="parse_query", max_tokens=600,
                response_format={"type": "json_object"}, retry_transient=False,
            )
            if finish_reason in {"length", "max_tokens"}:
                continue
            try:
                parsed = ParsedQuery.model_validate(json.loads(content))
                parsed.raw_query = query
                return parsed
            except (json.JSONDecodeError, ValidationError, TypeError):
                continue
        raise QueryParsingError("暂时无法可靠解析该需求，请重新描述关键参数。")

    def generate_grounded_answer(
        self, query: str, evidence: list[Evidence], structured_facts: dict[str, Any] | None = None
    ) -> str:
        if not evidence:
            return "当前知识库没有找到足够的官方证据支持该结论。"
        system = (
            "你是芯片技术资料解释器。只能依据 STRUCTURED FACTS 和 EVIDENCE 回答。"
            "不得虚构参数、页码或资料内容，不得把 UNKNOWN 变成 PASS。"
            "证据不足就明确说明；工程推断必须标记为推断。仅引用给定的 [E数字]，回答简洁，不输出推理过程。"
        )
        blocks = [f"[E{i}]\n{item.text[:800]}" for i, item in enumerate(evidence[:6], 1)]
        user = (f"USER QUERY:\n{query}\n\nSTRUCTURED FACTS:\n"
                f"{json.dumps(structured_facts or {}, ensure_ascii=False)}\n\nEVIDENCE:\n"
                + "\n\n".join(blocks))
        content, _ = self._chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            operation="grounded_answer", max_tokens=700, retry_transient=True,
        )
        return content.strip()

    def smoke(self) -> bool:
        content, _ = self._chat_completion(
            [{"role": "system", "content": "Reply with OK only."},
             {"role": "user", "content": "OK"}],
            operation="smoke", max_tokens=4, retry_transient=False,
        )
        return content.strip().upper() == "OK"

    def _chat_completion(
        self, messages: list[dict[str, str]], *, operation: str, max_tokens: int,
        response_format: dict[str, str] | None = None, retry_transient: bool = False,
    ) -> tuple[str, str | None]:
        if not self.api_key:
            raise ChatServiceError("config", "缺少 DEEPSEEK_API_KEY")
        body: dict[str, Any] = {
            "model": self.model, "messages": messages, "temperature": 0,
            "thinking": {"type": self.thinking}, "max_tokens": max_tokens, "stream": False,
        }
        if response_format:
            body["response_format"] = response_format
        attempts = 2 if retry_transient else 1
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                response = self._http.post(
                    "/chat/completions", json=body,
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                )
                if response.status_code in {401, 403}:
                    raise ChatServiceError("config", "DeepSeek API key 或权限无效")
                if response.status_code == 429:
                    raise ChatServiceError("rate_limit", "DeepSeek API 请求频率受限")
                if response.status_code >= 500:
                    raise ChatServiceError("temporary", "DeepSeek 服务暂时不可用")
                response.raise_for_status()
                payload = response.json()
                choice = payload["choices"][0]
                content = choice["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ChatServiceError("response", "DeepSeek 返回了空内容")
                self._emit_usage(payload, operation, time.perf_counter() - started, True)
                return content, choice.get("finish_reason")
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self._emit_usage({}, operation, time.perf_counter() - started, False)
                error = ChatServiceError("timeout", "DeepSeek 请求超时")
                if attempt + 1 == attempts:
                    raise error from exc
            except ChatServiceError as exc:
                self._emit_usage({}, operation, time.perf_counter() - started, False)
                if attempt + 1 == attempts or exc.kind not in {"rate_limit", "temporary"}:
                    raise
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                self._emit_usage({}, operation, time.perf_counter() - started, False)
                raise ChatServiceError("response", "DeepSeek 响应无效") from exc
        raise ChatServiceError("temporary", "DeepSeek 服务暂时不可用")

    def _emit_usage(self, payload: dict[str, Any], operation: str,
                    latency: float, success: bool) -> None:
        if not self.usage_sink:
            return
        usage = payload.get("usage") or {}
        try:
            self.usage_sink({
                "timestamp": int(time.time()), "model": self.model,
                "operation_type": operation,
                "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
                "output_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
                "total_tokens": usage.get("total_tokens"),
                "latency_ms": round(latency * 1000), "success": success,
            })
        except Exception:
            LOGGER.debug("usage sink failed", exc_info=True)


class OllamaEmbeddingClient:
    def __init__(self, *, base_url: str | None = None, model: str | None = None,
                 timeout: float = 60, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = (base_url or config_value("LCA_EMBED_BASE_URL") or
                         "http://127.0.0.1:11434").rstrip("/")
        self.model = model or config_value("LCA_EMBED_MODEL") or "qwen3-embedding:0.6b"
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout,
                                  transport=transport, trust_env=False)

    def close(self) -> None:
        self._http.close()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._http.post("/api/embed", json={"model": self.model, "input": texts})
        response.raise_for_status()
        vectors = response.json().get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError("Ollama embedding 响应数量不匹配")
        return vectors


# ASCII boundaries are deliberate: Python's ``\b`` treats adjacent Chinese
# characters as word characters and can truncate or miss a part number.
PART_RE = re.compile(
    r"(?<![A-Z0-9-])(?:MP[A-Z0-9]*\d[A-Z0-9]*|DEMO-[A-Z0-9-]+)(?![A-Z0-9-])",
    re.IGNORECASE,
)


def extract_part_numbers(query: str) -> list[str]:
    return list(dict.fromkeys(match.upper() for match in PART_RE.findall(query)))
