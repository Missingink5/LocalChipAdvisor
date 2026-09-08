"""One small end-to-end pipeline for the Hybrid Search MVP."""
from __future__ import annotations

import re
from typing import Any

from .llm import (
    ChatServiceError,
    DeepSeekChatClient,
    OllamaEmbeddingClient,
    extract_part_numbers,
)
from .models import AnswerResult, CheckState, Intent, ParsedQuery
from .retrieval import deterministic_select, hybrid_search
from .store import ChipStore

NO_EVIDENCE = "当前知识库没有找到足够的官方证据支持该结论。"


class ChipAdvisor:
    def __init__(self, store: ChipStore, chat: DeepSeekChatClient,
                 embedder: OllamaEmbeddingClient | None = None) -> None:
        self.store = store
        self.chat = chat
        self.embedder = embedder

    def answer(self, query: str) -> AnswerResult:
        parsed = self._route(query)
        if parsed.intent == Intent.PART_SELECTION:
            return self._selection(parsed)
        if parsed.intent == Intent.PART_COMPARE:
            return self._compare(parsed)
        return self._qa(parsed)

    def _route(self, query: str) -> ParsedQuery:
        parts = extract_part_numbers(query)
        lowered = query.casefold()
        if len(parts) >= 2 and any(word in lowered for word in ("比较", "对比", "compare", " vs ", " versus ")):
            return ParsedQuery(raw_query=query, intent=Intent.PART_COMPARE, part_numbers=parts)
        if parts:
            return ParsedQuery(raw_query=query, intent=Intent.PART_QA, part_numbers=parts,
                               semantic_query=query)
        return self.chat.parse_query(query)

    def _selection(self, parsed: ParsedQuery) -> AnswerResult:
        candidates = deterministic_select(self.store, parsed)[:5]
        formal = [item for item in candidates if item.overall == CheckState.PASS]
        unknown = [item for item in candidates if item.overall == CheckState.UNKNOWN]
        lines = ["满足全部硬约束："]
        lines.extend(f"- {item.product.part_number}" for item in formal)
        if not formal:
            lines.append("- 无")
        if unknown:
            lines.append("资料不足，不能列为正式满足：")
            lines.extend(f"- {item.product.part_number}" for item in unknown)
        return AnswerResult(intent=parsed.intent, parsed_query=parsed, candidates=candidates,
                            answer="\n".join(lines))

    def _qa(self, parsed: ParsedQuery) -> AnswerResult:
        product = (self.store.get_product_by_part_number(parsed.part_numbers[0])
                   if parsed.part_numbers else None)
        if product and product.reviewed:
            exact = _exact_structured_answer(parsed.raw_query, product)
            if exact:
                return AnswerResult(intent=parsed.intent, parsed_query=parsed, answer=exact)
        hits = hybrid_search(self.store, parsed, self.embedder)
        evidence = [hit.evidence for hit in hits]
        if not evidence:
            return AnswerResult(intent=parsed.intent, parsed_query=parsed, answer=NO_EVIDENCE)
        try:
            draft = self.chat.generate_grounded_answer(parsed.raw_query, evidence)
            answer, warnings = _bind_citations(draft, evidence)
        except ChatServiceError:
            answer = "检索已完成，但当前语言模型服务不可用，以下是找到的证据。"
            warnings = ["DeepSeek Chat 当前不可用；未生成技术结论。"]
        return AnswerResult(intent=parsed.intent, parsed_query=parsed, answer=answer,
                            evidence=evidence, warnings=warnings)

    def _compare(self, parsed: ParsedQuery) -> AnswerResult:
        products = [self.store.get_product_by_part_number(part) for part in parsed.part_numbers]
        products = [product for product in products if product and product.reviewed]
        if not products:
            return AnswerResult(intent=parsed.intent, parsed_query=parsed,
                                answer="没有找到这些型号的已审核结构化记录。")
        fields = ("vin_min_v", "vin_max_v", "vout_min_v", "vout_max_v", "iout_max_a",
                  "aec_q100", "i2c", "ocp", "ovp", "otp")
        lines = ["型号 | " + " | ".join(fields), "--- | " + " | ".join("---" for _ in fields)]
        for product in products:
            values = ["UNKNOWN" if getattr(product, field) is None else str(getattr(product, field))
                      for field in fields]
            lines.append(product.part_number + " | " + " | ".join(values))
        return AnswerResult(intent=parsed.intent, parsed_query=parsed, answer="\n".join(lines))


def _exact_structured_answer(query: str, product: Any) -> str | None:
    lowered = query.casefold()
    rules = [
        (("最大输入", "max input", "maximum input"), "vin_max_v", "V", "最大输入电压"),
        (("最大输出电流", "max output current", "maximum output current"), "iout_max_a", "A", "最大输出电流"),
        (("i2c",), "i2c", "", "I2C"),
        (("aec-q100", "aec q100"), "aec_q100", "", "AEC-Q100"),
    ]
    for terms, field, unit, label in rules:
        if any(term in lowered for term in terms):
            value = getattr(product, field)
            if value is None:
                return f"{product.part_number} 的 {label} 在已审核结构化数据中为 UNKNOWN，不能判定为支持。"
            if isinstance(value, bool):
                return f"{product.part_number} 的已审核结构化记录显示：{label}={'支持' if value else '不支持'}。"
            return f"{product.part_number} 的已审核结构化记录显示：{label}={value:g} {unit}。"
    return None


def _bind_citations(draft: str, evidence: list[Any]) -> tuple[str, list[str]]:
    valid = {f"E{i}": item for i, item in enumerate(evidence[:6], 1)}
    seen: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in valid:
            return ""
        if key not in seen:
            seen.append(key)
        return f"[{key}]"

    cleaned = re.sub(r"\[(E\d+)\]", replace, draft).strip()
    warnings: list[str] = []
    if not seen:
        warnings.append("模型未给出有效证据 ID；未接受其产品事实陈述。")
        cleaned = "模型回答缺少有效证据引用，以下仅展示检索证据。"
        seen = list(valid)[:3]
    citations = [
        f"[{key}] {valid[key].document_id}，第 {valid[key].page} 页"
        + (f"，{valid[key].section}" if valid[key].section else "")
        for key in seen
    ]
    return cleaned + "\n\n引用：\n" + "\n".join(citations), warnings
