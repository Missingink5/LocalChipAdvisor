"""Conversational, evidence-bound advisor service.

The service exposes:

* `handle_turn()` — the multi-turn entry point. Takes the current
  `ConversationState`, the user's new `UserTurn` and (optionally) a
  `selected_option_id` for clarification-button clicks. Returns the new
  state plus an `AnswerResult` (clarification is encoded as status
  NEEDS_CLARIFICATION with a non-null `clarification` field).

* `ask()` — kept for backwards compatibility with the legacy CLI, the
  evaluator and unit tests. It builds a transient empty state, runs a
  single turn, and renders the result in the old dict shape.

The service never stores per-user state in `self`. Conversation state lives
on the caller (the Streamlit session or the CLI driver) so different
browser sessions cannot contaminate each other.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .answering import (
    AnsweringEngine,
    evidence_set_hash_for,
    evidence_set_hash_for_records,
    run_answer_pipeline,
)
from .chat_client import ChatClient
from .contracts import (
    ALLOWED_PRODUCTS,
    AnswerGap,
    AnswerResult,
    ClarificationRequest,
    ConversationState,
    EvidenceBundle,
    EvidenceRecord,
    ResolvedIntent,
    UserTurn,
    gen_id,
)
from .conversation import apply_turn, new_session_state
from .index import Index
from .understanding import understand


PRODUCT = re.compile(
    r"(?<![A-Za-z0-9])(?:MP4570|TPS54331|TPS562201|TPS562208|LT8610)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Legacy exports kept for tests + the old CLI compatibility path.
# ---------------------------------------------------------------------------


class Selection(BaseModel):
    """Legacy evidence-selection model. Kept so tests still compile.

    The legacy `_chat(schema=Selection)` callers pass a Pydantic schema, so
    this class now subclasses BaseModel to preserve `.model_validate_json()`.
    """

    model_config = ConfigDict(extra="forbid")

    relevant_ids: list[str] = Field(default_factory=list, max_length=4)
    sufficient: bool = False
    conflict: bool = False


class Support(BaseModel):
    """Legacy evidence-support model. Kept so tests still compile."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = False
    correct_product: bool = False
    conditions_complete: bool = False
    conflict: bool = False


def validate_selection(draft: Selection, evidence: list[dict]) -> list[dict]:
    allowed = {r["chunk_id"]: r for r in evidence}
    if len(set(draft.relevant_ids)) != len(draft.relevant_ids):
        raise ValueError("Duplicate evidence ID")
    if any(i not in allowed for i in draft.relevant_ids):
        raise ValueError("Citation outside this request's evidence allowlist")
    return [allowed[i] for i in draft.relevant_ids]


def render_controlled_facts(query: str, selected: list[dict]) -> list[str]:
    """Legacy narrow-fact renderer. Not used by the new answer pipeline."""
    text = re.sub(r"\s+", "", "\n".join(r["text"] for r in selected).lower())
    facts: list[str] = []
    if (any(term in query.lower() for term in ("热", "烫", "thermal", "temperature", "hot", "温度"))
            and "thermalshutdown" in text and "typically170oc" in text
            and "below160oc" in text and "~10oc" in text):
        facts.append("MP4570 监测芯片结温；典型约 170°C 触发关断，结温降到 160°C 以下后恢复，典型迟滞约 10°C。")
    if (any(term in query.lower() for term in ("60v", "绝对最大", "absolute maximum", "正常工作"))
            and "absolutemaximumratings" in text and "supplyvoltagevin" in text
            and "60v" in text and "recommendedoperatingconditions" in text
            and "4.5vto55v" in text):
        facts.append("MP4570 的 60V 属于绝对最大额定值；资料列出的推荐工作输入范围为 4.5V–55V，不能把 60V 当作持续正常工作条件。")
    return facts


# ---------------------------------------------------------------------------
# Bundle construction
# ---------------------------------------------------------------------------


def build_bundle(index: Index, intent: ResolvedIntent,
                 query: str, max_records: int = 6) -> EvidenceBundle:
    products = intent.product_ids or []
    if not products:
        records: list[dict] = []
    else:
        try:
            records = index.search(query, products, mode="hybrid", top_k=max_records)
        except Exception as exc:  # noqa: BLE001 - retrieval boundary
            raise RuntimeError(f"检索失败：{type(exc).__name__}: {exc}") from exc
        product_set = {p.upper() for p in products}
        records = [
            r for r in records
            if {p.upper() for p in r.get("products", [])} & product_set
        ]
    bundle_records = [
        EvidenceRecord(
            chunk_id=r["chunk_id"],
            doc_id=r["doc_id"],
            text=r.get("raw_text") or r.get("text", ""),
            products=list(r.get("products", [])),
            document_sha256=r["document_sha256"],
            revision=str(r.get("revision", "")),
            page_start=int(r["page_start"]),
            page_end=int(r["page_end"]),
            source_url=str(r.get("source_url", "")),
        )
        for r in records
    ]
    build_id = index.manifest.get("build_id", "unknown")
    request_id = gen_id("req")
    set_hash = evidence_set_hash_for_records([
        (r.chunk_id, r.text) for r in bundle_records
    ])
    bundle = EvidenceBundle(
        build_id=build_id,
        request_id=request_id,
        intent_revision=intent.revision,
        resolved_query=intent.scope_text or query,
        original_user_texts=[query],
        records=bundle_records,
        evidence_set_hash=set_hash,
        scope_topic=intent.topic,
    )
    return bundle


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AdvisorService:
    def __init__(self, manifest: Path) -> None:
        self.index = Index(Path(manifest))
        self.chat = ChatClient(model="qwen3.5:9b-q4_K_M")
        self.engine = AnsweringEngine(self.chat)
        self.build_id = self.index.manifest.get("build_id", "unknown")
        self.manifest_path = Path(manifest).resolve()

    # ----- Multi-turn -----

    def handle_turn(
        self,
        state: ConversationState,
        user_turn: UserTurn,
        *,
        selected_option_id: str | None = None,
    ) -> tuple[ConversationState, AnswerResult]:
        """Apply one user turn to the conversation state.

        Returns the updated state plus an `AnswerResult`. When the user must
        be asked a clarification question, the result has status
        `NEEDS_CLARIFICATION` and a populated `clarification` field.
        """
        proposal: dict | None = None
        if user_turn.text.strip():
            history_payload = [
                {"turn_id": t.turn_id, "text": t.text}
                for t in state.user_turns[-4:]
            ]
            try:
                proposal = self.engine.propose_intent(
                    user_turn.turn_id, user_turn.text, history_payload,
                )
            except Exception:
                proposal = None
            if isinstance(proposal, dict) and "product_ids" in proposal:
                proposal["product_ids"] = _sanitize_products(proposal["product_ids"])

        decision = apply_turn(
            state, user_turn,
            intent_proposal=proposal,
            selected_option_id=selected_option_id,
        )
        if decision.clarification is not None:
            return decision.state, self._clarification_to_result(decision.clarification)
        if decision.intent is None:
            return decision.state, AnswerResult(
                status="MODEL_ERROR",
                answer_text="",
                message="会话决策异常：既无澄清也无意图。",
                build_id=self.build_id,
            )

        intent = decision.intent
        query = intent.scope_text or user_turn.text
        try:
            bundle = build_bundle(self.index, intent, query)
        except Exception as exc:  # noqa: BLE001
            return decision.state, AnswerResult(
                status="RETRIEVAL_ERROR",
                answer_text="",
                message=f"检索失败：{type(exc).__name__}: {exc}",
                build_id=self.build_id,
                intent_revision=intent.revision,
            )
        if not bundle.records:
            return decision.state, AnswerResult(
                status="INSUFFICIENT_EVIDENCE",
                answer_text="本次检索到的资料不足以回答该问题。",
                unanswered_scopes=[AnswerGap(
                    kind="missing_evidence",
                    scope_zh=intent.scope_text or user_turn.text,
                )],
                build_id=self.build_id,
                intent_revision=intent.revision,
                message="资料中未命中与问题相关的片段。",
                limitations=["本次检索为空，已自动拒答。"],
            )
        result, _diagnostics = run_answer_pipeline(intent, bundle, self.engine)
        if not result.message:
            result.message = {
                "ANSWERED": "找到支持回答的证据。",
                "PARTIAL_ANSWER": "部分证据不足以完整回答。",
                "INSUFFICIENT_EVIDENCE": "资料不足，未能给出有证据的答案。",
                "SOURCE_CONFLICT": "资料存在冲突，已自动拒答。",
                "MODEL_ERROR": "本地模型输出未能通过验证。",
                "OUT_OF_SCOPE": "问题超出当前文档问答范围。",
                "NEEDS_CLARIFICATION": "需要澄清后再回答。",
            }.get(result.status, "本次回答未通过验证。")
        return decision.state, result

    # ----- Legacy single-turn -----

    def ask(self, query: str, retrieval_only: bool = False) -> dict:
        """Backwards-compatible single-turn entry point."""
        started = time.perf_counter()
        result: dict = {
            "status": "INSUFFICIENT_EVIDENCE",
            "message": "本次证据不足以回答。",
            "parameters": [], "evidence": [], "quotes": [],
            "rendered_facts": [],
            "build_id": self.build_id,
            "timings": {}, "engineering_result": "未进行正式工程合格判定。",
            "limitations": ["本次为单轮调用，未继承会话上下文。"],
        }
        if not query.strip() or len(query) > 4000:
            result.update(status="NEEDS_CLARIFICATION", message="请输入不超过4000字的问题。")
            return result
        parsed = understand(query)
        if parsed["ambiguities"]:
            result.update(status="NEEDS_CLARIFICATION", message="；".join(parsed["ambiguities"]))
            return result
        if not parsed["products"]:
            result.update(status="NEEDS_CLARIFICATION", message=(
                "请输入型号：MP4570、TPS54331、TPS562201、TPS562208 或 LT8610。"
                if not parsed.get("selection")
                else "已提取明确参数，请确认型号后查询资料；尚未确认的条件不会用于正式选型。"
            ))
            return result

        session_id = gen_id("legacy")
        state = new_session_state(session_id)
        try:
            state, full = self.handle_turn(state, UserTurn(turn_id=gen_id("turn"), text=query))
        except Exception as exc:  # noqa: BLE001
            result.update(status="RETRIEVAL_ERROR", message=f"本地服务无法启动：{type(exc).__name__}: {exc}")
            return result
        result.update(
            status=full.status,
            message=full.message,
            answer_text=full.answer_text,
            claims=[c.model_dump() for c in full.claims],
            citations=[c.model_dump() for c in full.citations],
            unanswered_scopes=[g.model_dump() for g in full.unanswered_scopes],
            limitations=list(full.limitations),
            clarification=full.clarification.model_dump() if full.clarification else None,
        )
        result["evidence"] = self._evidence_dicts(full)
        result["quotes"] = [{"chunk_id": c.chunk_id, "text": c.quote or ""} for c in full.citations]
        if retrieval_only:
            result["status"] = "RETRIEVED"
        result["timings"]["total_seconds"] = round(time.perf_counter() - started, 3)
        return result

    # ----- Helpers -----

    def _evidence_dicts(self, result: AnswerResult) -> list[dict]:
        out: list[dict] = []
        for citation in result.citations:
            record = self.index.by_id.get(citation.chunk_id)
            if record is None:
                continue
            out.append(dict(record))
        return out

    def _clarification_to_result(self, clarification: ClarificationRequest) -> AnswerResult:
        return AnswerResult(
            status="NEEDS_CLARIFICATION",
            answer_text="",
            clarification=clarification,
            unanswered_scopes=[AnswerGap(
                kind="missing_user_condition",
                scope_zh=clarification.question,
            )],
            build_id=self.build_id,
            intent_revision=clarification.intent_revision,
            message=clarification.question,
            limitations=["等待用户澄清后继续。"],
        )


# ---------------------------------------------------------------------------
# Helpers used by the service
# ---------------------------------------------------------------------------


def _sanitize_products(product_ids: list) -> list[str]:
    cleaned: list[str] = []
    for product in product_ids:
        match = PRODUCT.search(str(product))
        if not match:
            continue
        up = match.group().upper()
        if up in ALLOWED_PRODUCTS and up not in cleaned:
            cleaned.append(up)
    return cleaned
