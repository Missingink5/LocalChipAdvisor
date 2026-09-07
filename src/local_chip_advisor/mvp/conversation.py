"""Conversation state machine: how user turns turn into resolved intents.

The key contract:
  - apply_turn() is the single entry point.
  - It returns ConversationDecision containing either a clarification OR a
    ResolvedIntent — never both, never neither.
  - The user's previous question is preserved on pending_question so that a
    short follow-up like "MP4570" or "第一项" attaches to the right intent.

Selection rules:
  - ClarificationReplySelection: user clicked an option_id for the current
    pending_clarification; only valid when the option belongs to that
    request.
  - FreeTextResolution: user wrote free text; we attempt regex extraction
    before consulting the model for ambiguous cases.
  - NewTopicReset: user wrote something clearly unrelated to the pending
    question; we reset the pending clarification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .contracts import (
    ALLOWED_REASONS,
    ClarificationRequest,
    ConversationState,
    ResolvedIntent,
    UserTurn,
    gen_id,
)

PRODUCT = re.compile(r"(?<![A-Za-z0-9])(?:MP4570|TPS54331|TPS562201|TPS562208|LT8610)(?![A-Za-z0-9])", re.IGNORECASE)

# Topic / scope heuristics used by the FREE-TEXT path. The chat model is used
# only when these heuristics cannot resolve the intent.
SCOPE_KEYWORDS = {
    "thermal_shutdown": ("太热", "过温", "热关断", "thermal", "temperature", "烫"),
    "soft_start": ("软启动", "soft start", "soft-start", "爬升", "上电"),
    "quiescent_current": ("静态电流", "空载", "自己耗", "quiescent"),
    "light_load": ("轻载", "pulse-skipping", "轻负载", "light load"),
    "power_good": ("PG", "power good", "电源就绪"),
    "uvp": ("欠压", "UVP", "undervoltage"),
    "ovp": ("过压", "OVP", "overvoltage"),
    "absolute_maximum": ("绝对最大", "absolute maximum", "极限"),
    "vin_range": ("输入范围", "vin", "VIN"),
    "vout_range": ("输出范围", "vout", "VOUT"),
    "efficiency": ("效率", "efficiency"),
    "switching_frequency": ("频率", "frequency"),
    "current_limit": ("限流", "current limit", "峰值"),
    "en_logic": ("EN", "使能", "enable"),
    "package": ("封装", "package"),
}


@dataclass
class ConversationDecision:
    state: ConversationState
    clarification: ClarificationRequest | None = None
    intent: ResolvedIntent | None = None


def _detect_topic(text: str) -> str:
    lowered = text.lower()
    for topic, kws in SCOPE_KEYWORDS.items():
        if any(kw.lower() in lowered for kw in kws):
            return topic
    return "other"


def _extract_products(text: str) -> list[str]:
    seen: list[str] = []
    for match in PRODUCT.finditer(text):
        up = match.group().upper()
        if up not in seen:
            seen.append(up)
    return seen


def _build_intent(text: str, *, products: list[str], topic: str | None = None,
                  basis: str = "explicit_request",
                  source_text_for_ref: str | None = None) -> ResolvedIntent:
    inferred_topic = topic or _detect_topic(text)
    scope_text = text.strip()
    return ResolvedIntent(
        kind="document_qa",
        product_ids=products,
        topic=inferred_topic,
        scope_text=scope_text,
        source_refs=[],
        resolution_basis=basis,
        revision=0,
    )


def _explicit_product_answer(text: str) -> ResolvedIntent | None:
    """Detect "MP4570" alone → inherit the previously pending question/topic.

    Only valid when there is a pending_question in the conversation. If there
    are multiple products in history we cannot infer which one the user
    meant, so we return None and the caller asks for clarification.
    """
    products = _extract_products(text)
    text_stripped = text.strip()
    if not products:
        return None
    # The user wrote exactly one product identifier (no extra Chinese/English
    # content that would change the scope).
    if not PRODUCT.fullmatch(text_stripped):
        return None
    return _build_intent(text, products=products, basis="clarification_reply")


def _option_selection(text: str, state: ConversationState) -> ResolvedIntent | None:
    if not state.pending_clarification:
        return None
    if state.pending_clarification.options and text.strip() in {
        opt.label for opt in state.pending_clarification.options
    }:
        for opt in state.pending_clarification.options:
            if opt.label == text.strip():
                return _resolve_option_text(opt.proposed_value, state)
    if text.strip() in {"第一项", "第一个", "1", "one", "选项1"}:
        if state.pending_clarification.options:
            opt = state.pending_clarification.options[0]
            return _resolve_option_text(opt.proposed_value, state)
    if text.strip() in {"第二项", "第二个", "2", "two", "选项2"}:
        if len(state.pending_clarification.options) >= 2:
            opt = state.pending_clarification.options[1]
            return _resolve_option_text(opt.proposed_value, state)
    if text.strip() in {"第三项", "第三个", "3", "three", "选项3"}:
        if len(state.pending_clarification.options) >= 3:
            opt = state.pending_clarification.options[2]
            return _resolve_option_text(opt.proposed_value, state)
    return None


def _resolve_option_text(proposed: str, state: ConversationState) -> ResolvedIntent | None:
    """Map a proposed option value to a structured intent.

    For topic-clarification options the proposed value embeds a topic marker
    like "topic:over_temp_protection". For product options we extract the
    product identifier from the proposed text.
    """
    products = _extract_products(proposed)
    if proposed.startswith("topic:"):
        topic = proposed.split(":", 1)[1]
        merged_question = state.pending_question or proposed
        return ResolvedIntent(
            kind="document_qa",
            product_ids=state.resolved_intent.product_ids if state.resolved_intent else [],
            topic=topic,
            scope_text=merged_question,
            source_refs=[],
            resolution_basis="explicit_option_selection",
            revision=(state.resolved_intent.revision + 1) if state.resolved_intent else 1,
        )
    if products:
        topic = state.resolved_intent.topic if state.resolved_intent else "other"
        merged_question = state.pending_question or "针对该型号的查询"
        return ResolvedIntent(
            kind="document_qa",
            product_ids=products,
            topic=topic,
            scope_text=merged_question,
            source_refs=[],
            resolution_basis="explicit_option_selection",
            revision=(state.resolved_intent.revision + 1) if state.resolved_intent else 1,
        )
    return None


def _looks_like_new_topic(text: str, state: ConversationState) -> bool:
    if not state.pending_question:
        return False
    prev = state.pending_question
    # If the new text introduces a topic word absent from the previous question
    # AND does NOT mention any product the previous question mentioned, treat
    # as new topic.
    prev_products = set(_extract_products(prev))
    new_products = set(_extract_products(text))
    if new_products and new_products.isdisjoint(prev_products):
        return True
    prev_topic = _detect_topic(prev)
    new_topic = _detect_topic(text)
    if new_topic not in {"other", prev_topic}:
        # Different topic and the new text isn't a one-word clarification.
        tokens = re.findall(r"[A-Za-z0-9]+|[一-鿿]", text)
        if len(tokens) >= 4:
            return True
    return False


def _make_clarification(reason: str, question: str,
                        options: list[tuple[str, str, str]],
                        state: ConversationState,
                        target_field: str) -> ClarificationRequest:
    return ClarificationRequest(
        request_id=gen_id("cl"),
        intent_revision=state.revision,
        reason=reason,
        question=question,
        options=[{"option_id": oid, "label": label, "proposed_value": val}
                 for oid, label, val in options],
        target_field=target_field,
    )


def apply_turn(state: ConversationState, user_turn: UserTurn,
               *, intent_proposal: dict[str, Any] | None = None,
               selected_option_id: str | None = None) -> ConversationDecision:
    """Mutate state according to the user turn and decide what's next."""
    state.user_turns.append(user_turn)
    if len(state.user_turns) > 8:
        state.user_turns = state.user_turns[-8:]

    text = user_turn.text
    new_revision = state.revision + 1

    # Explicit option click: even if user_turn is empty, an option_id can
    # resolve the pending clarification.
    if selected_option_id and state.pending_clarification:
        if any(opt.option_id == selected_option_id for opt in state.pending_clarification.options):
            opt = next(opt for opt in state.pending_clarification.options
                       if opt.option_id == selected_option_id)
            intent = _resolve_option_text(opt.proposed_value, state)
            if intent is not None:
                intent.revision = new_revision
                state.resolved_intent = intent
                state.pending_clarification = None
                state.phase = "READY"
                state.revision = new_revision
                return ConversationDecision(state=state, intent=intent)

    if state.pending_clarification:
        option_intent = _option_selection(text, state)
        if option_intent is not None:
            option_intent.revision = new_revision
            state.resolved_intent = option_intent
            state.pending_clarification = None
            state.phase = "READY"
            state.revision = new_revision
            return ConversationDecision(state=state, intent=option_intent)

    # Brand new question, possibly replacing pending state.
    previous_pending = state.pending_question
    state.pending_question = text

    if _looks_like_new_topic(text, state):
        state.pending_clarification = None

    products = _extract_products(text)
    explicit_topic = _detect_topic(text) if products else None
    # Bare product like "MP4570" → inherit previous question/topic if any.
    if not products and state.resolved_intent and state.resolved_intent.product_ids:
        products = list(state.resolved_intent.product_ids)
        explicit_topic = state.resolved_intent.topic
    bare_product_match = _explicit_product_answer(text)
    if bare_product_match and previous_pending and previous_pending != text:
        bare_product_match.revision = new_revision
        bare_product_match.scope_text = previous_pending
        bare_product_match.topic = state.resolved_intent.topic if state.resolved_intent else "other"
        state.resolved_intent = bare_product_match
        state.pending_clarification = None
        state.phase = "READY"
        state.revision = new_revision
        return ConversationDecision(state=state, intent=bare_product_match)

    # If we have a clear product + clear topic, the intent is ready.
    if products and explicit_topic and explicit_topic != "other":
        intent = ResolvedIntent(
            kind="document_qa", product_ids=products, topic=explicit_topic,
            scope_text=text, source_refs=[],
            resolution_basis="explicit_request", revision=new_revision,
        )
        state.resolved_intent = intent
        state.pending_clarification = None
        state.phase = "READY"
        state.revision = new_revision
        return ConversationDecision(state=state, intent=intent)

    # If a chat proposal was supplied (LLM), use it for ambiguous cases.
    if intent_proposal is not None:
        try:
            proposal = _proposal_to_intent(intent_proposal, text, new_revision)
        except (ValidationError, KeyError, ValueError):
            proposal = None
        if proposal is not None:
            if proposal.ambiguous:
                clarification = _clarify_from_proposal(proposal, state)
                if clarification is not None:
                    state.pending_clarification = clarification
                    state.phase = "AWAITING_CLARIFICATION"
                    state.revision = new_revision
                    return ConversationDecision(state=state, clarification=clarification)
            state.resolved_intent = proposal
            state.pending_clarification = None
            state.phase = "READY"
            state.revision = new_revision
            return ConversationDecision(state=state, intent=proposal)

    # Deterministic fallback: ask for the missing field.
    if not products:
        clarification = _make_clarification(
            reason="missing_product",
            question="请告诉我具体的芯片型号，例如 MP4570、TPS54331、TPS562201、TPS562208 或 LT8610。",
            options=[
                ("opt_mp4570", "MP4570", "MP4570"),
                ("opt_tps54331", "TPS54331", "TPS54331"),
                ("opt_tps562201", "TPS562201", "TPS562201"),
                ("opt_tps562208", "TPS562208", "TPS562208"),
            ][:3],
            state=state, target_field="product_ids",
        )
        state.pending_clarification = clarification
        state.phase = "AWAITING_CLARIFICATION"
        state.revision = new_revision
        return ConversationDecision(state=state, clarification=clarification)

    # We have a product but the topic is unclear.
    clarification = _make_clarification(
        reason="ambiguous_topic",
        question="你想了解该芯片的哪方面？",
        options=[
            ("opt_topic_thermal", "过温保护", "topic:thermal_shutdown"),
            ("opt_topic_soft", "软启动", "topic:soft_start"),
            ("opt_topic_light", "轻载行为", "topic:light_load"),
        ],
        state=state, target_field="topic",
    )
    state.pending_clarification = clarification
    state.phase = "AWAITING_CLARIFICATION"
    state.revision = new_revision
    return ConversationDecision(state=state, clarification=clarification)


def _proposal_to_intent(proposal: dict[str, Any], text: str, revision: int) -> ResolvedIntent | None:
    if not isinstance(proposal, dict):
        return None
    kind = proposal.get("kind", "document_qa")
    if kind not in {"document_qa", "product_comparison", "requirement_extraction", "mixed", "out_of_scope"}:
        return None
    products = proposal.get("product_ids") or []
    if not isinstance(products, list):
        return None
    products = [str(p).upper() for p in products]
    topic = str(proposal.get("topic", "other"))
    scope_text = str(proposal.get("scope_text", text))
    basis = str(proposal.get("resolution_basis", "explicit_request"))
    ambiguous = bool(proposal.get("ambiguous"))
    missing_reason = proposal.get("missing_reason")
    if missing_reason not in ALLOWED_REASONS:
        missing_reason = None
    return ResolvedIntent(
        kind=kind, product_ids=products, topic=topic,
        scope_text=scope_text, source_refs=[],
        resolution_basis=basis, revision=revision,
        ambiguous=ambiguous, missing_reason=missing_reason,
    )


def _clarify_from_proposal(proposal: ResolvedIntent, state: ConversationState) -> ClarificationRequest | None:
    reason = proposal.missing_reason or "ambiguous_topic"
    if reason == "missing_product":
        return _make_clarification(
            reason=reason,
            question="请告诉我具体芯片型号，例如 MP4570、TPS54331、TPS562201、TPS562208 或 LT8610。",
            options=[
                ("opt_mp4570", "MP4570", "MP4570"),
                ("opt_tps54331", "TPS54331", "TPS54331"),
                ("opt_tps562201", "TPS562201", "TPS562201"),
            ],
            state=state, target_field="product_ids",
        )
    if reason == "ambiguous_topic":
        return _make_clarification(
            reason=reason,
            question="你主要想了解该芯片的哪方面？",
            options=[
                ("opt_topic_thermal", "过温保护", "topic:thermal_shutdown"),
                ("opt_topic_soft", "软启动", "topic:soft_start"),
                ("opt_topic_light", "轻载行为", "topic:light_load"),
            ],
            state=state, target_field="topic",
        )
    if reason == "ambiguous_reference":
        return _make_clarification(
            reason=reason,
            question="你指的是哪一颗芯片？请明确型号。",
            options=[
                ("opt_mp4570", "MP4570", "MP4570"),
                ("opt_tps54331", "TPS54331", "TPS54331"),
                ("opt_tps562201", "TPS562201", "TPS562201"),
            ],
            state=state, target_field="product_ids",
        )
    return _make_clarification(
        reason="missing_user_condition",
        question="请补充更具体的条件，使我能找到准确的资料。",
        options=[],
        state=state, target_field="scope_text",
    )


def new_session_state(session_id: str) -> ConversationState:
    return ConversationState(session_id=session_id)
