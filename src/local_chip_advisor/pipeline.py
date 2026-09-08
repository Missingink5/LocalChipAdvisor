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
        evidence = []
        required_sources = [
            {"vin_v": "vin_max_v", "vout_v": "vout_max_v"}.get(c.field, c.field)
            for c in parsed.constraints if c.hard
        ]
        if parsed.topology:
            required_sources.append("topology")
        for candidate in candidates:
            if candidate.overall != CheckState.PASS:
                continue
            missing = []
            for field in required_sources:
                matches = self.store.evidence_for_field(candidate.product.product_id, field)
                if not matches:
                    missing.append(field)
                    candidate.checks[f"evidence:{field}"] = CheckState.UNKNOWN
                    continue
                if matches[0].evidence_id not in {item.evidence_id for item in evidence}:
                    evidence.append(matches[0])
            if missing:
                candidate.overall = CheckState.UNKNOWN
        formal = [item for item in candidates if item.overall == CheckState.PASS]
        unknown = [item for item in candidates if item.overall == CheckState.UNKNOWN]
        lines = ["满足全部硬约束："]
        for item in formal:
            markers = [f"[E{i}]" for i, known in enumerate(evidence, 1)
                       if known.product_id == item.product.product_id]
            lines.append(f"- {item.product.part_number} {' '.join(markers)}".rstrip())
        if not formal:
            lines.append("- 无")
        if unknown:
            lines.append("资料不足，不能列为正式满足：")
            lines.extend(f"- {item.product.part_number}" for item in unknown)
        citations = [f"[E{i}] {item.document_id}，第 {item.page} 页，{item.section or '未标注章节'}"
                     for i, item in enumerate(evidence, 1)]
        if citations:
            lines.extend(["", "引用：", *citations])
        return AnswerResult(intent=parsed.intent, parsed_query=parsed, candidates=candidates,
                            answer="\n".join(lines), evidence=evidence)

    def _qa(self, parsed: ParsedQuery) -> AnswerResult:
        product = (self.store.get_product_by_part_number(parsed.part_numbers[0])
                   if parsed.part_numbers else None)
        if product and product.reviewed:
            exact = _exact_structured_answer(parsed.raw_query, product)
            if exact:
                answer, field_name = exact
                if getattr(product, field_name) is None:
                    return AnswerResult(
                        intent=parsed.intent, parsed_query=parsed, answer=answer,
                        warnings=[f"字段 {field_name} 当前为 UNKNOWN。"],
                    )
                evidence = self.store.evidence_for_field(product.product_id, field_name)[:1]
                if evidence:
                    item = evidence[0]
                    answer += (f"\n\n引用：\n[E1] {item.document_id}，第 {item.page} 页"
                               + (f"，{item.section}" if item.section else ""))
                    return AnswerResult(intent=parsed.intent, parsed_query=parsed,
                                        answer=answer, evidence=evidence)
                return AnswerResult(
                    intent=parsed.intent, parsed_query=parsed,
                    answer="结构化记录存在，但缺少对应的已审核证据，暂不输出确定结论。",
                    warnings=[f"字段 {field_name} 缺少证据绑定。"],
                )
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
        fields = ("vin_min_v", "vin_max_v", "vout_min_v", "vout_max_v",
                  "iout_max_a", "aec_q100", "package_type")
        source_fields = {
            "vin_min_v": "vin_max_v", "vin_max_v": "vin_max_v",
            "vout_min_v": "vout_max_v", "vout_max_v": "vout_max_v",
            "iout_max_a": "iout_max_a", "aec_q100": "aec_q100",
            "package_type": "package_type",
        }
        evidence = []
        lines = ["型号 | " + " | ".join(fields), "--- | " + " | ".join("---" for _ in fields)]
        for product in products:
            values = []
            for field in fields:
                value = getattr(product, field)
                if value is None:
                    values.append("UNKNOWN")
                    continue
                matches = self.store.evidence_for_field(product.product_id, source_fields[field])
                if not matches:
                    values.append("UNVERIFIED")
                    continue
                item = matches[0]
                if item.evidence_id not in {known.evidence_id for known in evidence}:
                    evidence.append(item)
                marker = f"E{next(i for i, known in enumerate(evidence, 1) if known.evidence_id == item.evidence_id)}"
                values.append(f"{value} [{marker}]")
            lines.append(product.part_number + " | " + " | ".join(values))
        citations = [f"[E{i}] {item.document_id}，第 {item.page} 页，{item.section or '未标注章节'}"
                     for i, item in enumerate(evidence, 1)]
        answer = "\n".join(lines) + ("\n\n引用：\n" + "\n".join(citations) if citations else "")
        return AnswerResult(intent=parsed.intent, parsed_query=parsed,
                            answer=answer, evidence=evidence)


def _exact_structured_answer(query: str, product: Any) -> tuple[str, str] | None:
    lowered = query.casefold()
    rules = [
        (("最大输入", "max input", "maximum input"), "vin_max_v", "V", "最大输入电压"),
        (("最大输出电流", "max output current", "maximum output current"), "iout_max_a", "A", "最大输出电流"),
        (("i2c",), "i2c", "", "I2C"),
        (("aec-q100", "aec q100"), "aec_q100", "", "AEC-Q100"),
        (("package", "封装"), "package_type", "", "封装"),
        (("是否支持ovp", "过压保护吗"), "ovp", "", "OVP"),
        (("是否支持uvlo", "欠压锁定吗"), "uvlo", "", "UVLO"),
        (("是否支持otp", "过温保护吗"), "otp", "", "OTP"),
    ]
    for terms, field, unit, label in rules:
        if any(term in lowered for term in terms):
            value = getattr(product, field)
            if value is None:
                return (f"{product.part_number} 的 {label} 在已审核结构化数据中为 UNKNOWN，不能判定为支持。", field)
            if isinstance(value, bool):
                return (f"{product.part_number} 的已审核结构化记录显示：{label}={'支持' if value else '不支持'}。", field)
            if isinstance(value, str):
                return (f"{product.part_number} 的已审核结构化记录显示：{label}={value}。", field)
            return (f"{product.part_number} 的已审核结构化记录显示：{label}={value:g} {unit}。", field)
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
