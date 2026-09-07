"""Data contracts for the conversational evidence-bound advisor.

All structured outputs (intent, evidence, draft claims, audits, final result)
go through these models. The contract is the single source of truth: the chat
client may not invent field names, page numbers, URLs or build IDs.

Models are intentionally strict (extra='forbid', bounded lengths) so a
malformed chat output cannot be smuggled past validation. Numeric and
qualifier bindings exist so the hard validator can catch missing values even
when the model tries to keep them in prose.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_CLAIMS = 4
MAX_GAPS = 2
MAX_QUOTES = 12
MAX_REVISIONS = 1
ALLOWED_KINDS = (
    "document_fact",
    "rule_result",
)
ALLOWED_REASONS = (
    "missing_product",
    "ambiguous_reference",
    "ambiguous_topic",
    "ambiguous_parameter_role",
    "ambiguous_comparison",
    "missing_user_condition",
)
ALLOWED_TOPICS = (
    "thermal_shutdown",
    "soft_start",
    "quiescent_current",
    "light_load",
    "power_good",
    "uvp",
    "ovp",
    "absolute_maximum",
    "vin_range",
    "vout_range",
    "efficiency",
    "switching_frequency",
    "current_limit",
    "en_logic",
    "package",
    "other",
)
ALLOWED_INTENT_KINDS = (
    "document_qa",
    "product_comparison",
    "requirement_extraction",
    "mixed",
    "out_of_scope",
)
ALLOWED_VALUE_KINDS = ("typical", "min", "max", "range", "nominal", "unknown")
ALLOWED_VERDICTS = ("supported", "unsupported", "uncertain")
ALLOWED_PROBLEM_CODES = (
    "wrong_product",
    "wrong_value",
    "wrong_unit",
    "wrong_role",
    "missing_condition",
    "unsupported_inference",
    "scope_mismatch",
    "citation_not_supporting",
    "evidence_conflict",
    "wrong_value_kind",
    "numeric_binding_missing",
)
ALLOWED_STATUSES = (
    "ANSWERED",
    "PARTIAL_ANSWER",
    "NEEDS_CLARIFICATION",
    "INSUFFICIENT_EVIDENCE",
    "SOURCE_CONFLICT",
    "MODEL_ERROR",
    "RETRIEVAL_ERROR",
    "OUT_OF_SCOPE",
)
ALLOWED_PHASES = ("IDLE", "AWAITING_CLARIFICATION", "READY")
ALLOWED_RESOLUTION_BASIS = (
    "explicit_request",
    "clarification_reply",
    "explicit_option_selection",
    "inherited_from_history",
)
ALLOWED_ROLES = (
    "junction_shutdown_trigger",
    "junction_recovery_threshold",
    "junction_hysteresis",
    "ambient_temperature",
    "absolute_maximum_vin",
    "recommended_min_vin",
    "recommended_max_vin",
    "continuous_output_current",
    "peak_output_current",
    "current_limit",
    "soft_start_time",
    "uvp_threshold",
    "ovp_threshold",
    "switching_frequency_min",
    "switching_frequency_max",
    "quiescent_current",
    "other",
)

ALLOWED_PRODUCTS = ("MP4570", "TPS54331", "TPS562201", "TPS562208", "LT8610")


class SourceRef(BaseModel):
    """Pointer into a user turn's text using Python character offsets."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    source_text: str = Field(max_length=600)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, end: int, info) -> int:
        start = info.data.get("start", 0)
        if end <= start:
            raise ValueError("source ref end must be greater than start")
        return end


class UserTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str
    text: str = Field(default="", min_length=0, max_length=4000)


class ResolvedIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["document_qa", "product_comparison", "requirement_extraction", "mixed", "out_of_scope"]
    product_ids: list[str] = Field(max_length=4)
    topic: str = Field(default="other", max_length=80)
    scope_text: str = Field(default="", max_length=400)
    source_refs: list[SourceRef] = Field(default_factory=list, max_length=4)
    resolution_basis: Literal[
        "explicit_request", "clarification_reply", "explicit_option_selection", "inherited_from_history"
    ] = "explicit_request"
    revision: int = 0
    ambiguous: bool = False
    missing_reason: str | None = None

    @field_validator("product_ids")
    @classmethod
    def _no_duplicates(cls, products: list[str]) -> list[str]:
        seen: list[str] = []
        for pid in products:
            up = pid.upper()
            if up not in seen:
                seen.append(up)
        return seen


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str = Field(max_length=40)
    label: str = Field(max_length=200)
    proposed_value: str = Field(max_length=200)


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(max_length=60)
    intent_revision: int = Field(ge=0)
    reason: Literal[
        "missing_product",
        "ambiguous_reference",
        "ambiguous_topic",
        "ambiguous_parameter_role",
        "ambiguous_comparison",
        "missing_user_condition",
    ]
    question: str = Field(min_length=1, max_length=300)
    options: list[ClarificationOption] = Field(default_factory=list, max_length=3)
    target_field: str = Field(max_length=60)


class ConversationState(BaseModel):
    """Per-session state. NEVER share between Streamlit sessions."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(max_length=60)
    phase: Literal["IDLE", "AWAITING_CLARIFICATION", "READY"] = "IDLE"
    user_turns: list[UserTurn] = Field(default_factory=list, max_length=12)
    pending_question: str | None = None
    resolved_intent: ResolvedIntent | None = None
    pending_clarification: ClarificationRequest | None = None
    resolved_fields: dict[str, str] = Field(default_factory=dict)
    revision: int = 0


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=200)
    doc_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)
    products: list[str] = Field(default_factory=list, max_length=6)
    document_sha256: str = Field(min_length=8, max_length=128)
    revision: str = Field(default="", max_length=40)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    source_url: str = Field(default="", max_length=400)


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_id: str = Field(max_length=120)
    request_id: str = Field(max_length=60)
    intent_revision: int = Field(ge=0)
    resolved_query: str = Field(max_length=400)
    original_user_texts: list[str] = Field(default_factory=list, max_length=4)
    records: list[EvidenceRecord] = Field(default_factory=list, max_length=MAX_QUOTES)
    evidence_set_hash: str = Field(max_length=120)
    scope_topic: str = Field(default="other", max_length=80)


class NumericBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_value: str = Field(max_length=40)
    unit: str = Field(max_length=20)
    role: str = Field(max_length=60)
    evidence_id: str = Field(min_length=1, max_length=200)
    source_quote: str = Field(min_length=1, max_length=400)
    value_kind: Literal["typical", "min", "max", "range", "nominal", "unknown"] = "typical"


class QualifierBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description_zh: str = Field(min_length=1, max_length=200)
    evidence_id: str = Field(min_length=1, max_length=200)
    source_quote: str = Field(min_length=1, max_length=400)


class EvidenceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=400)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=60)
    text_zh: str = Field(min_length=1, max_length=400)
    kind: Literal["document_fact", "rule_result"] = "document_fact"
    product_ids: list[str] = Field(default_factory=list, max_length=4)
    evidence_ids: list[str] = Field(default_factory=list, max_length=4)
    anchors: list[EvidenceAnchor] = Field(default_factory=list, max_length=4)
    numeric_bindings: list[NumericBinding] = Field(default_factory=list, max_length=4)
    qualifier_bindings: list[QualifierBinding] = Field(default_factory=list, max_length=4)

    @field_validator("claim_id")
    @classmethod
    def _claim_id_format(cls, value: str) -> str:
        if not re.fullmatch(r"claim_[A-Za-z0-9_]+", value):
            raise ValueError("claim_id must be claim_<token>")
        return value


class AnswerGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["missing_evidence", "missing_user_condition", "unsupported_derivation"]
    scope_zh: str = Field(min_length=1, max_length=200)


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=60)
    draft_hash: str = Field(default="", max_length=120)
    claims: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    coverage: Literal["complete", "partial", "none"] = "partial"
    gaps: list[AnswerGap] = Field(default_factory=list, max_length=MAX_GAPS)

    @field_validator("claims")
    @classmethod
    def _unique_claim_ids(cls, claims: list[Claim]) -> list[Claim]:
        ids = [c.claim_id for c in claims]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate claim_id in draft")
        return claims


class ClaimReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=60)
    verdict: Literal["supported", "unsupported", "uncertain"]
    problem_codes: list[str] = Field(default_factory=list, max_length=4)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=4)
    note_zh: str = Field(default="", max_length=300)

    @field_validator("problem_codes")
    @classmethod
    def _normalize_problem_codes(cls, codes: list[str]) -> list[str]:
        for code in codes:
            if code not in ALLOWED_PROBLEM_CODES:
                raise ValueError(f"Unknown problem code: {code}")
        return codes


class AnswerReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, max_length=60)
    review_hash: str = Field(default="", max_length=120)
    draft_hash: str = Field(default="", max_length=120)
    evidence_set_hash: str = Field(default="", max_length=120)
    claim_reviews: list[ClaimReview] = Field(default_factory=list, max_length=MAX_CLAIMS + 4)
    answers_question: bool = False
    coverage: Literal["complete", "partial", "none"] = "partial"
    conflicts: list[str] = Field(default_factory=list, max_length=4)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marker: str = Field(min_length=1, max_length=6)
    chunk_id: str = Field(min_length=1, max_length=200)
    doc_id: str = Field(min_length=1, max_length=200)
    revision: str = Field(default="", max_length=40)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    source_url: str = Field(default="", max_length=400)
    quote: str = Field(default="", max_length=400)
    products: list[str] = Field(default_factory=list, max_length=4)


class AnswerResult(BaseModel):
    """Final result returned to UI/CLI. Backwards-compatible fields are kept
    so old evaluate scripts do not crash, but new UI must use answer_text."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "ANSWERED", "PARTIAL_ANSWER", "NEEDS_CLARIFICATION",
        "INSUFFICIENT_EVIDENCE", "SOURCE_CONFLICT", "MODEL_ERROR",
        "RETRIEVAL_ERROR", "OUT_OF_SCOPE",
    ]
    answer_text: str = Field(default="", max_length=2000)
    claims: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    citations: list[Citation] = Field(default_factory=list, max_length=MAX_QUOTES)
    clarification: ClarificationRequest | None = None
    unanswered_scopes: list[AnswerGap] = Field(default_factory=list, max_length=MAX_GAPS)
    build_id: str = Field(default="", max_length=120)
    intent_revision: int = 0
    timings: dict[str, float] = Field(default_factory=dict)
    message: str = Field(default="", max_length=400)
    engineering_result: str = Field(default="未进行正式工程合格判定。", max_length=400)
    limitations: list[str] = Field(default_factory=list, max_length=4)
    # Compatibility fields consumed by legacy callers/UI/tests.
    parameters: list[dict] = Field(default_factory=list, max_length=8)
    evidence: list[dict] = Field(default_factory=list, max_length=MAX_QUOTES)
    quotes: list[dict] = Field(default_factory=list, max_length=MAX_QUOTES)
    rendered_facts: list[str] = Field(default_factory=list, max_length=MAX_CLAIMS)

    @field_validator("answer_text")
    @classmethod
    def _no_fake_citations(cls, value: str) -> str:
        # Strip hand-written citations like [99] that the model might invent.
        cleaned = re.sub(r"\[(\d{1,3})\]", "", value)
        return cleaned.strip()


def gen_id(prefix: str) -> str:
    import secrets

    return f"{prefix}_{secrets.token_hex(6)}"
