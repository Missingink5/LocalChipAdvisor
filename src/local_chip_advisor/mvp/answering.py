"""Generation + audit + revision orchestration.

This module is the *only* place that decides whether an AnswerDraft becomes
the final AnswerResult. The flow is:

  draft = generate(intent, bundle)
  issues = run_hard_validation(draft, bundle)
  review = audit(intent, bundle, draft)
  if issues or any(review verdict is unsupported):
      draft = revise_once(intent, bundle, draft, issues, review)
      issues, review = rerun_hard_and_audit(draft, bundle, intent)
  status, answer_text, citations = finalize(draft, review, bundle)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from pydantic import ValidationError

from .answer_validation import (
    HardIssue,
    consolidate_claims_for_render,
    run_hard_validation,
)
from .chat_client import ChatClient, ChatError
from .contracts import (
    AnswerDraft,
    AnswerGap,
    AnswerResult,
    AnswerReview,
    Claim,
    Citation,
    EvidenceBundle,
    ResolvedIntent,
    gen_id,
)
from .prompts import (
    AUDIT_SYSTEM,
    GENERATION_SYSTEM,
    REVISION_SYSTEM,
    audit_json_schema,
    audit_user_payload,
    generation_json_schema,
    generation_user_payload,
    revision_user_payload,
    understanding_json_schema,
    understanding_user_payload,
    UNDERSTANDING_SYSTEM,
)

LOGGER = logging.getLogger(__name__)


def _hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def draft_hash_for(draft: AnswerDraft) -> str:
    payload = {
        "claims": [c.model_dump() for c in draft.claims],
        "coverage": draft.coverage,
        "gaps": [g.model_dump() for g in draft.gaps],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def evidence_set_hash_for(bundle: EvidenceBundle) -> str:
    return evidence_set_hash_for_records([(r.chunk_id, r.text) for r in bundle.records])


def evidence_set_hash_for_records(records: list[tuple[str, str]]) -> str:
    ids = sorted({cid for cid, _ in records})
    texts = sorted(
        hashlib.sha256(text.encode("utf-8")).hexdigest() for _, text in records
    )
    return hashlib.sha256((json.dumps(ids) + "|" + "|".join(texts)).encode("utf-8")).hexdigest()[:32]


def render_claims(claims: list[Claim], citations: list[Citation]) -> str:
    """Concatenate the supported claim sentences into the user-facing text.

    The program — not the model — adds citation markers after the sentence
    where each chunk_id first appears. Citation markers are stable per
    (build_id, chunk_id) within this AnswerResult.
    """
    marker_for: dict[str, str] = {c.chunk_id: c.marker for c in citations}
    rendered: list[str] = []
    for claim in claims:
        markers = sorted({marker_for.get(eid, "") for eid in claim.evidence_ids if marker_for.get(eid)})
        suffix = "[" + ", ".join(m.strip("[]") for m in markers if m) + "]" if markers else ""
        rendered.append(claim.text_zh + (suffix if suffix and suffix != "[]" else ""))
    return "\n\n".join(rendered)


def collect_citations(draft: AnswerDraft, bundle: EvidenceBundle) -> list[Citation]:
    """Build stable citation markers from the claims' evidence_ids."""
    by_id = {r.chunk_id: r for r in bundle.records}
    seen: dict[str, str] = {}
    citations: list[Citation] = []
    counter = 1
    for claim in draft.claims:
        for evidence_id in claim.evidence_ids:
            if evidence_id in seen:
                continue
            if evidence_id not in by_id:
                continue
            record = by_id[evidence_id]
            seen[evidence_id] = f"[{counter}]"
            citations.append(Citation(
                marker=seen[evidence_id],
                chunk_id=record.chunk_id,
                doc_id=record.doc_id,
                revision=record.revision,
                page_start=record.page_start,
                page_end=record.page_end,
                source_url=record.source_url,
                products=record.products,
                quote="",
            ))
            counter += 1
    return citations


def parse_draft(payload: dict[str, Any]) -> AnswerDraft:
    """Hydrate a chat payload into AnswerDraft, attaching draft_hash."""
    payload = dict(payload)
    payload.setdefault("claims", [])
    payload.setdefault("coverage", "partial")
    payload.setdefault("gaps", [])
    payload.setdefault("draft_id", gen_id("draft"))
    draft = AnswerDraft.model_validate(payload)
    # Inject deterministic hash based on claims+gaps+coverage (not on
    # draft_id, since the model picks those).
    object.__setattr__(draft, "draft_hash", draft_hash_for(draft))
    return draft


def parse_review(payload: dict[str, Any], draft: AnswerDraft,
                 evidence_hash: str) -> AnswerReview:
    payload = dict(payload)
    payload.setdefault("review_id", gen_id("review"))
    payload.setdefault("claim_reviews", [])
    payload.setdefault("answers_question", False)
    payload.setdefault("coverage", draft.coverage)
    payload.setdefault("conflicts", [])
    review = AnswerReview.model_validate(payload)
    object.__setattr__(review, "draft_hash", draft.draft_hash)
    object.__setattr__(review, "evidence_set_hash", evidence_hash)
    return review


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


class AnsweringEngine:
    def __init__(self, chat: ChatClient) -> None:
        self.chat = chat

    def propose_intent(self, user_turn_id: str, text: str,
                       history: list[dict]) -> dict[str, Any]:
        payload = understanding_user_payload(user_turn_id, text, history)
        return self.chat.chat(
            UNDERSTANDING_SYSTEM, payload, understanding_json_schema(),
            num_predict=600, temperature=0.0,
        )

    def generate_draft(self, intent: ResolvedIntent, bundle: EvidenceBundle) -> AnswerDraft:
        payload = generation_user_payload(intent, bundle)
        result = self.chat.chat(
            GENERATION_SYSTEM, payload, generation_json_schema(),
            num_predict=2200, temperature=0.0,
        )
        return parse_draft(result)

    def revise_draft(self, intent: ResolvedIntent, bundle: EvidenceBundle,
                     draft: AnswerDraft, issues: list[HardIssue],
                     review: AnswerReview | None) -> AnswerDraft:
        problems = [
            {"code": i.code, "scope": i.scope, "detail": i.detail}
            for i in issues
        ]
        if review is not None:
            for cr in review.claim_reviews:
                for code in cr.problem_codes:
                    problems.append({"code": code, "scope": cr.claim_id, "detail": cr.note_zh})
        payload = revision_user_payload(problems, intent, bundle, draft)
        result = self.chat.chat(
            REVISION_SYSTEM, payload, generation_json_schema(),
            num_predict=2200, temperature=0.0,
        )
        return parse_draft(result)

    def audit_draft(self, intent: ResolvedIntent, bundle: EvidenceBundle,
                    draft: AnswerDraft) -> AnswerReview:
        payload = audit_user_payload(intent.scope_text or "用户已确认的问题", draft, bundle)
        result = self.chat.chat(
            AUDIT_SYSTEM, payload, audit_json_schema(),
            num_predict=900, temperature=0.0,
        )
        return parse_review(result, draft, evidence_set_hash_for(bundle))


def finalize_answer(intent: ResolvedIntent, bundle: EvidenceBundle,
                    draft: AnswerDraft, review: AnswerReview) -> AnswerResult:
    """Decide the final AnswerResult from a draft + review pair."""
    citations = collect_citations(draft, bundle)
    supported = consolidate_claims_for_render(draft, review)

    if not supported:
        # Determine a specific cause for the empty answer.
        if any(g.kind == "missing_evidence" for g in draft.gaps) or draft.coverage == "none":
            status = "INSUFFICIENT_EVIDENCE"
            text = "本次检索到的资料不足以回答该问题。"
        elif any(cr.verdict == "uncertain" for cr in review.claim_reviews):
            status = "INSUFFICIENT_EVIDENCE"
            text = "本次资料对相关数据存在歧义，未能给出明确答案。"
        elif any(cr.verdict == "unsupported" for cr in review.claim_reviews):
            status = "INSUFFICIENT_EVIDENCE"
            text = "本次生成的陈述未能通过证据核验，未给出答案。"
        else:
            status = "INSUFFICIENT_EVIDENCE"
            text = "本次未能生成可发布的回答。"
        # Surface gaps as unanswered scopes.
        gaps = list(draft.gaps) if draft.gaps else [AnswerGap(
            kind="missing_evidence", scope_zh=intent.scope_text or "用户已确认的范围",
        )]
        return AnswerResult(
            status=status, answer_text=text, claims=[], citations=citations,
            unanswered_scopes=gaps, build_id=bundle.build_id,
            intent_revision=intent.revision, message=text,
            limitations=["未通过事实级证据核验；如需进一步判断，请补充更具体的问题。"],
        )

    status = "ANSWERED" if review.answers_question else "PARTIAL_ANSWER"
    if not review.answers_question:
        status = "PARTIAL_ANSWER"

    text = render_claims(supported, citations)
    if draft.gaps:
        text += "\n\n未回答范围：" + "；".join(g.scope_zh for g in draft.gaps)

    limitations = [
        "资料问答，不构成正式工程合格判定。",
        "所有事实均绑定至本次 evidence_id；其他型号或条件不在本次范围内。",
    ]
    return AnswerResult(
        status=status, answer_text=text, claims=supported,
        citations=citations, unanswered_scopes=list(draft.gaps),
        build_id=bundle.build_id, intent_revision=intent.revision,
        message="", limitations=limitations,
    )


def run_answer_pipeline(intent: ResolvedIntent, bundle: EvidenceBundle,
                        engine: AnsweringEngine,
                        *, max_revisions: int = 1) -> tuple[AnswerResult, dict]:
    """Drive draft → audit → (optional revision) → finalize.

    Returns the AnswerResult and a diagnostics dict (stage timings, attempts).
    """
    timings: dict[str, float] = {}
    attempts: list[dict] = []

    def _record(stage: str, status: str, started: float, **extra) -> None:
        timings[stage + "_seconds"] = round(time.perf_counter() - started, 3)
        attempts.append({"stage": stage, "status": status, **extra})

    started = time.perf_counter()
    try:
        draft = engine.generate_draft(intent, bundle)
    except (ChatError, ValidationError, ValueError) as exc:
        _record("generation", "failed", started, error=str(exc))
        return _model_error_result(bundle, intent, exc), {"timings": timings, "attempts": attempts}
    _record("generation", "ok", started, claims=len(draft.claims))

    started = time.perf_counter()
    issues = run_hard_validation(draft, bundle)
    _record("hard_validation", "issues" if issues else "ok", started, count=len(issues))

    started = time.perf_counter()
    try:
        review = engine.audit_draft(intent, bundle, draft)
    except (ChatError, ValidationError, ValueError) as exc:
        _record("audit", "failed", started, error=str(exc))
        return _model_error_result(bundle, intent, exc), {"timings": timings, "attempts": attempts}
    _record("audit", "ok", started)

    if (issues or any(cr.verdict != "supported" for cr in review.claim_reviews)) and max_revisions > 0:
        started = time.perf_counter()
        try:
            draft = engine.revise_draft(intent, bundle, draft, issues, review)
        except (ChatError, ValidationError, ValueError) as exc:
            _record("revision", "failed", started, error=str(exc))
            return _model_error_result(bundle, intent, exc), {"timings": timings, "attempts": attempts}
        _record("revision", "ok", started, claims=len(draft.claims))
        issues = run_hard_validation(draft, bundle)
        started = time.perf_counter()
        try:
            review = engine.audit_draft(intent, bundle, draft)
        except (ChatError, ValidationError, ValueError) as exc:
            _record("revision_audit", "failed", started, error=str(exc))
            return _model_error_result(bundle, intent, exc), {"timings": timings, "attempts": attempts}
        _record("revision_audit", "ok", started)

    started = time.perf_counter()
    result = finalize_answer(intent, bundle, draft, review)
    _record("finalize", result.status, started)

    return result, {"timings": timings, "attempts": attempts, "issues": [i.__dict__ for i in issues]}


def _model_error_result(bundle: EvidenceBundle, intent: ResolvedIntent, exc: Exception) -> AnswerResult:
    detail = str(exc)[:300]
    return AnswerResult(
        status="MODEL_ERROR", answer_text="", claims=[], citations=[],
        unanswered_scopes=[AnswerGap(kind="missing_evidence",
                                    scope_zh=intent.scope_text or "用户已确认的范围")],
        build_id=bundle.build_id, intent_revision=intent.revision,
        message=f"模型输出未通过处理：{detail}",
        limitations=["模型响应缺失或不合规。"],
    )
