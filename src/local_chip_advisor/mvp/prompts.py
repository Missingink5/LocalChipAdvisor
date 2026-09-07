"""Prompts for the three chat stages: understanding, generation, audit.

Each prompt is versioned. The prompts do not borrow few-shot examples from the
sealed gold/holdout datasets. No prompt may instruct the model to produce
build IDs, page numbers, or engineering pass verdicts — those fields are
populated by the program.

The previous "No free-text answer" policy is intentionally removed from the
generation prompt: the new contract is that the model produces a structured
AnswerDraft whose Chinese claims ARE the answer rendered to the user.
"""
from __future__ import annotations

import json
from typing import Any

from .contracts import (
    ALLOWED_INTENT_KINDS,
    ALLOWED_REASONS,
    ALLOWED_TOPICS,
    ALLOWED_VALUE_KINDS,
    ALLOWED_ROLES,
    AnswerDraft,
    AnswerReview,
    Claim,
    EvidenceBundle,
    ResolvedIntent,
)


UNDERSTANDING_SYSTEM = """You analyze the user's latest question and (optionally) the
clarification context the user is replying to. You never answer the question
about the chip; you only propose what the user is asking.

Output a JSON object matching IntentProposal. Do not include any text outside
the JSON.

Rules:
1. product_ids: list of explicit product identifiers present in the user's
   text. Allowed identifiers: MP4570, TPS54331, TPS562201, TPS562208, LT8610.
   Use the exact uppercase form. Do NOT invent products. If the user refers
   to "it" / "它" and only one product is unambiguous in the conversation,
   you may set product_ids to that single product and resolution_basis =
   "inherited_from_history". Otherwise set ambiguous=true with reason
   "missing_product" or "ambiguous_reference".
2. topic: choose one short topic label from the allowed list. If none fit,
   set "other".
3. scope_text: a short Chinese phrase describing the user's specific scope.
4. ambiguous: true if any required field is missing; otherwise false.
5. missing_reason: one of "missing_product", "ambiguous_reference",
   "ambiguous_topic", "ambiguous_parameter_role", "ambiguous_comparison",
   "missing_user_condition". Only set when ambiguous=true.
6. source_refs: pointers into the user turn's text justifying the fields.
   Every claim about the user must point to the actual characters in the
   user turn. Use turn_id as provided.
7. resolution_basis: explicit_request | clarification_reply |
   explicit_option_selection | inherited_from_history.
8. Never mark resolved=true; that is the program's responsibility.
"""


def understanding_user_payload(user_turn_id: str, text: str, history: list[dict]) -> dict[str, Any]:
    return {
        "user_turn_id": user_turn_id,
        "user_text": text,
        "history_turns": history,
        "allowed_product_ids": ["MP4570", "TPS54331", "TPS562201", "TPS562208", "LT8610"],
        "allowed_topics": list(ALLOWED_TOPICS),
        "allowed_reasons": list(ALLOWED_REASONS),
        "allowed_kinds": list(ALLOWED_INTENT_KINDS),
    }


def understanding_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(ALLOWED_INTENT_KINDS)},
            "product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            "topic": {"type": "string", "maxLength": 80},
            "scope_text": {"type": "string", "maxLength": 400},
            "ambiguous": {"type": "boolean"},
            "missing_reason": {"type": "string", "enum": list(ALLOWED_REASONS)},
            "resolution_basis": {"type": "string", "enum": [
                "explicit_request", "clarification_reply",
                "explicit_option_selection", "inherited_from_history",
            ]},
            "source_refs": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "turn_id": {"type": "string"},
                        "start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 0},
                        "source_text": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["turn_id", "start", "end", "source_text"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["kind", "product_ids", "topic", "scope_text", "ambiguous", "source_refs", "resolution_basis"],
        "additionalProperties": False,
    }


GENERATION_SYSTEM = """You are a precise, evidence-bound semiconductor datasheet
assistant. You produce a structured AnswerDraft that will be rendered as the
final answer to the user. The Chinese claim sentences ARE the answer; the
program will not rewrite them.

Hard rules — ignoring them produces a rejected draft:
1. Every claim must reference at least one evidence_id from the provided
   EvidenceBundle. Citation IDs from prior turns, other builds, or made-up
   strings are forbidden.
2. Each EvidenceAnchor.quote MUST appear verbatim (after whitespace/soft-
   hyphen normalization) inside its evidence_id's text. Do not stitch
   fragments from different paragraphs together.
3. NumericBinding.claim_value + unit + role + value_kind MUST match the
   evidence. value_kind ∈ typical|min|max|range|nominal|unknown. If the
   source says "typically" you MUST set value_kind=typical. If the source
   says "absolute maximum" you MUST set value_kind=max.
4. NumericBindings must list every numeric value (with its unit) that
   appears in the Chinese claim text and originates from the cited
   evidence. Missing a binding will fail validation.
5. Roles must match the source: a binding from "junction temperature"
   text cannot be ambient_temperature; a binding from "peak current"
   text cannot be continuous_output_current.
6. Never claim unconditional safety ("绝不会损坏", "guaranteed safe").
7. Never claim engineering suitability — that is the advisor's job, not
   the chat model's.
8. If the evidence is insufficient for the user's scope, set coverage to
   "none" or "partial" and explain the gap in `gaps`. Do not invent
   functions the chip does not have.
9. Always answer in concise Chinese (1-4 claims, 80-220 中文字).
10. Do NOT generate page numbers, build IDs, source URLs, or handbook
    citation markers like [1]. The program assigns those.
11. Never inherit numbers/values from assistant chat history.
12. Always include the conditions/limits stated in the source (Typical vs
    guaranteed, junction vs ambient, recommended vs absolute maximum).
13. Output ONLY the JSON object matching AnswerDraftSchema. No preamble.
"""


def generation_user_payload(intent: ResolvedIntent, bundle: EvidenceBundle) -> dict[str, Any]:
    return {
        "confirmed_question": intent.scope_text or "用户已确认的问题",
        "topic": intent.topic,
        "products": intent.product_ids,
        "evidence": [
            {
                "evidence_id": r.chunk_id,
                "doc_id": r.doc_id,
                "revision": r.revision,
                "products": r.products,
                "page_start": r.page_start,
                "page_end": r.page_end,
                "text": r.text,
            }
            for r in bundle.records
        ],
        "schema_hints": {
            "max_claims": 4,
            "allowed_kinds": ["document_fact"],
            "allowed_value_kinds": list(ALLOWED_VALUE_KINDS),
            "allowed_roles": list(ALLOWED_ROLES),
        },
    }


def generation_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            "claims": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string", "pattern": "^claim_[A-Za-z0-9_]+$"},
                        "text_zh": {"type": "string", "maxLength": 400},
                        "kind": {"type": "string", "enum": ["document_fact", "rule_result"]},
                        "product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                        "anchors": {
                            "type": "array",
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "evidence_id": {"type": "string"},
                                    "quote": {"type": "string", "maxLength": 400},
                                },
                                "required": ["evidence_id", "quote"],
                                "additionalProperties": False,
                            },
                        },
                        "numeric_bindings": {
                            "type": "array",
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "claim_value": {"type": "string", "maxLength": 40},
                                    "unit": {"type": "string", "maxLength": 20},
                                    "role": {"type": "string", "maxLength": 60},
                                    "evidence_id": {"type": "string"},
                                    "source_quote": {"type": "string", "maxLength": 400},
                                    "value_kind": {"type": "string", "enum": list(ALLOWED_VALUE_KINDS)},
                                },
                                "required": ["claim_value", "unit", "role", "evidence_id", "source_quote", "value_kind"],
                                "additionalProperties": False,
                            },
                        },
                        "qualifier_bindings": {
                            "type": "array",
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description_zh": {"type": "string", "maxLength": 200},
                                    "evidence_id": {"type": "string"},
                                    "source_quote": {"type": "string", "maxLength": 400},
                                },
                                "required": ["description_zh", "evidence_id", "source_quote"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["claim_id", "text_zh", "kind", "product_ids", "evidence_ids"],
                    "additionalProperties": False,
                },
            },
            "coverage": {"type": "string", "enum": ["complete", "partial", "none"]},
            "gaps": {
                "type": "array",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["missing_evidence", "missing_user_condition", "unsupported_derivation"]},
                        "scope_zh": {"type": "string", "maxLength": 200},
                    },
                    "required": ["kind", "scope_zh"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["draft_id", "claims", "coverage", "gaps"],
        "additionalProperties": False,
    }


AUDIT_SYSTEM = """You are a strict claim-level auditor for an evidence-bound
semiconductor advisor. You audit every claim produced by the generator; you do
NOT generate new claims. Output JSON only, matching AuditSchema.

For each claim, evaluate:
1. Does the cited evidence really support the Chinese sentence? Look at the
   claim text, the anchors, and the numeric bindings. The evidence text must
   contain the quoted phrases verbatim.
2. Does the claim mix in the wrong product? Multi-product datasheets share
   text; verify that the quoted paragraphs explicitly apply to the product
   listed in the claim.
3. Are numbers, units, value_kind and roles consistent? Typical vs Absolute
   Maximum vs Recommended Operating Conditions are different grades; the
   role must match the source (junction vs ambient, continuous vs peak,
   trigger vs recovery).
4. Are critical conditions preserved? If the source says "typically", the
   claim must not promote the value to a guaranteed rating. If the source
   specifies a junction temperature, the claim must not write it as ambient.
5. Did the model turn "no evidence found" into "the chip has no OVP"?
   Missing evidence is not a proof of absence.
6. Does the answer address the user's confirmed scope? An evidence-bound
   claim that is technically true but unrelated to the asked question
   should be flagged with scope_mismatch.
7. Did the model add unconditional safety guarantees? Those must be
   rejected.

Verdict meanings:
- supported: every required check passes. supporting_evidence_ids MUST list
  the evidence_ids that justify the claim.
- unsupported: any structural or factual check fails. problem_codes MUST
  list the failing codes.
- uncertain: evidence is ambiguous or partial; you cannot tell.

answers_question is true only if the supported claims collectively answer the
user's confirmed scope. coverage is complete|partial|none.
"""


def audit_user_payload(question: str, draft: AnswerDraft, bundle: EvidenceBundle) -> dict[str, Any]:
    return {
        "question": question,
        "claims": [c.model_dump() for c in draft.claims],
        "evidence": [
            {
                "evidence_id": r.chunk_id,
                "doc_id": r.doc_id,
                "products": r.products,
                "revision": r.revision,
                "page_start": r.page_start,
                "page_end": r.page_end,
                "text": r.text,
            }
            for r in bundle.records
        ],
        "allowed_verdicts": ["supported", "unsupported", "uncertain"],
        "allowed_problem_codes": [
            "wrong_product", "wrong_value", "wrong_unit", "wrong_role",
            "missing_condition", "unsupported_inference", "scope_mismatch",
            "citation_not_supporting", "evidence_conflict", "wrong_value_kind",
            "numeric_binding_missing",
        ],
    }


def audit_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "review_id": {"type": "string"},
            "claim_reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string", "pattern": "^claim_[A-Za-z0-9_]+$"},
                        "verdict": {"type": "string", "enum": ["supported", "unsupported", "uncertain"]},
                        "problem_codes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "supporting_evidence_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "note_zh": {"type": "string", "maxLength": 300},
                    },
                    "required": ["claim_id", "verdict", "problem_codes", "supporting_evidence_ids"],
                    "additionalProperties": False,
                },
            },
            "answers_question": {"type": "boolean"},
            "coverage": {"type": "string", "enum": ["complete", "partial", "none"]},
            "conflicts": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 4,
            },
        },
        "required": ["review_id", "claim_reviews", "answers_question", "coverage", "conflicts"],
        "additionalProperties": False,
    }


REVISION_SYSTEM = """You are revising an AnswerDraft whose previous audit found
specific problems. You must produce a NEW AnswerDraft that fixes those
problems. Treat the problems as a strict checklist: every code listed must
be resolved in the revised draft.

You may NOT introduce new claims that are not supported by the same
EvidenceBundle. You may shorten, rephrase, drop a claim, or correct a
numeric binding; you may not widen the scope.

Output JSON only, matching AnswerDraftSchema (same as the generation prompt).
"""


def revision_user_payload(problems: list[dict], intent: ResolvedIntent,
                         bundle: EvidenceBundle, draft: AnswerDraft) -> dict[str, Any]:
    return {
        "previous_draft": draft.model_dump(),
        "problem_codes": problems,
        "confirmed_question": intent.scope_text or "用户已确认的问题",
        "products": intent.product_ids,
        "evidence": [
            {
                "evidence_id": r.chunk_id,
                "doc_id": r.doc_id,
                "products": r.products,
                "page_start": r.page_start,
                "page_end": r.page_end,
                "text": r.text,
            }
            for r in bundle.records
        ],
    }
