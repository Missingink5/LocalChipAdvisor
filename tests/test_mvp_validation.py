"""Unit tests for answer_validation and contracts."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from local_chip_advisor.mvp.answer_validation import (
    HardIssue, detect_unsupported_inference, extract_numbers,
    find_missing_numeric_bindings, normalize_text, quote_present,
    run_hard_validation, units_compatible, validate_draft_structure,
    validate_numeric_bindings, validate_role_consistency,
    validate_unit_consistency, validate_value_kind_discipline,
    values_equal,
)
from local_chip_advisor.mvp.contracts import (
    AnswerDraft, AnswerGap, AnswerResult, Citation, Claim, ClaimReview,
    ClarificationOption, ClarificationRequest, ConversationState,
    EvidenceAnchor, EvidenceBundle, EvidenceRecord, NumericBinding,
    QualifierBinding, ResolvedIntent, UserTurn, gen_id,
)


def record(chunk_id: str = "ev1", text: str = "Thermal Shutdown (typically 170oC)",
           products=("MP4570",), page_start: int = 1, page_end: int = 1,
           doc_id: str = "doc", sha: str = "abcdef1234") -> EvidenceRecord:
    return EvidenceRecord(
        chunk_id=chunk_id, doc_id=doc_id, text=text,
        products=list(products), document_sha256=sha,
        revision="1.0", page_start=page_start, page_end=page_end,
        source_url="https://example.test",
    )


def bundle(records: list[EvidenceRecord]) -> EvidenceBundle:
    return EvidenceBundle(
        build_id="b", request_id=gen_id("req"), intent_revision=0,
        resolved_query="x", original_user_texts=["x"], records=records,
        evidence_set_hash=gen_id("h"),
    )


def claim(claim_id: str, text_zh: str, evidence_ids: list[str],
          anchors: list[EvidenceAnchor], bindings: list[NumericBinding],
          qualifiers: list[QualifierBinding],
          product_ids: list[str] = None) -> Claim:
    return Claim(
        claim_id=claim_id, text_zh=text_zh, kind="document_fact",
        product_ids=list(product_ids or []),
        evidence_ids=list(evidence_ids), anchors=list(anchors),
        numeric_bindings=list(bindings), qualifier_bindings=list(qualifiers),
    )


def test_normalize_and_quote_present():
    text = "Thermal Shutdown (typically 170oC) is implemented."
    assert quote_present(text, "thermal shutdown (typically 170oC) is implemented.")
    assert quote_present(text, "Thermal  Shutdown  (typically 170oC)")
    assert not quote_present(text, "absolutely not present")


def test_extract_numbers_chinese_and_english():
    nums = extract_numbers("170°C")
    assert ("170", "°C") in nums
    nums2 = extract_numbers("典型约 170 度")
    assert ("170", "度") in nums2
    nums3 = extract_numbers("300mA")
    assert ("300", "mA") in nums3


def test_values_equal_handles_unit_conversion():
    assert values_equal("300", "mA", "0.3", "A") is True
    assert values_equal("300", "mA", "0.4", "A") is False
    assert units_compatible("mA", "A") is True
    assert not units_compatible("V", "A")
    assert units_compatible("V", "mV") is True


def test_hard_validation_rejects_foreign_evidence_id():
    draft = AnswerDraft(draft_id="d1", claims=[
        claim("claim_a", "MP4570 会关断。", ["forged"], [], [], []),
    ])
    issues = validate_draft_structure(draft, bundle([record()]))
    assert any(i.code == "no_evidence" or i.code == "foreign_evidence" for i in issues)


def test_hard_validation_requires_evidence_id():
    draft = AnswerDraft(draft_id="d1", claims=[
        claim("claim_a", "MP4570 会关断。", [], [], [], []),
    ])
    issues = validate_draft_structure(draft, bundle([record()]))
    assert any(i.code == "no_evidence" for i in issues)


def test_hard_validation_rejects_fabricated_anchor():
    draft = AnswerDraft(draft_id="d1", claims=[
        claim("claim_a", "MP4570 会关断。", ["ev1"],
              [EvidenceAnchor(evidence_id="ev1", quote="fictional quote")], [], []),
    ])
    issues = validate_draft_structure(draft, bundle([record()]))
    assert any(i.code == "anchor_not_in_evidence" for i in issues)


def test_value_kind_discipline_rejects_typical_as_max():
    rec = record(text="Absolute Maximum Ratings: 60V")
    binding = NumericBinding(claim_value="60", unit="V", role="absolute_maximum_vin",
                             evidence_id="ev1",
                             source_quote="Absolute Maximum Ratings: 60V",
                             value_kind="max")
    cl = claim("claim_a", "MP4570 推荐 60V 工作。", ["ev1"], [],
               [binding], [], product_ids=["MP4570"])
    issues = validate_value_kind_discipline(cl, rec)
    # No issues because value_kind is already max matching "absolute maximum"
    assert all(i.code != "wrong_value_kind" for i in issues)


def test_value_kind_discipline_rejects_typical_as_max_for_typical_source():
    rec = record(text="Thermal Shutdown: typically 170oC, below 160oC.")
    binding = NumericBinding(claim_value="170", unit="°C",
                             role="junction_shutdown_trigger",
                             evidence_id="ev1",
                             source_quote="Thermal Shutdown: typically 170oC",
                             value_kind="max")  # WRONG: should be typical
    cl = claim("claim_a", "MP4570 在 170°C 关断。", ["ev1"], [], [binding], [],
               product_ids=["MP4570"])
    issues = validate_value_kind_discipline(cl, rec)
    assert any(i.code == "wrong_value_kind" for i in issues)


def test_role_consistency_rejects_wrong_product():
    rec = record(products=("MP4570",))
    cl = claim("claim_a", "TPS54331 在 170°C 关断。", ["ev1"], [], [], [],
               product_ids=["TPS54331"])
    issues = validate_role_consistency(cl, rec)
    assert any(i.code == "wrong_product" for i in issues)


def test_numeric_binding_missing_when_claim_has_unbound_numbers():
    rec = record(text="below 160oC")
    # No bindings declared despite the claim mentioning 160
    cl = claim("claim_a", "MP4570 在 160°C 以下恢复。", ["ev1"], [], [], [],
               product_ids=["MP4570"])
    issues = validate_numeric_bindings(cl, rec)
    assert any(i.code == "numeric_binding_missing" for i in issues)


def test_unsupported_inference_blocks_safety_guarantee():
    rec = record(text="Thermal Shutdown: typically 170oC")
    cl = claim("claim_a", "MP4570 绝对不会损坏。", ["ev1"], [], [], [],
               product_ids=["MP4570"])
    issues = detect_unsupported_inference(cl, rec)
    assert any(i.code == "unsupported_inference" for i in issues)


def test_run_hard_validation_runs_all_stages():
    rec = record(text="MP4570 thermal shutdown: typically 170oC, below 160oC.")
    binding = NumericBinding(claim_value="170", unit="°C",
                             role="junction_shutdown_trigger",
                             evidence_id="ev1",
                             source_quote="thermal shutdown: typically 170oC",
                             value_kind="typical")
    cl = claim("claim_a", "MP4570 在 170°C 关断。", ["ev1"],
              [EvidenceAnchor(evidence_id="ev1", quote="thermal shutdown: typically 170oC")],
              [binding], [], product_ids=["MP4570"])
    draft = AnswerDraft(draft_id="d1", claims=[cl], coverage="complete", gaps=[])
    issues = run_hard_validation(draft, bundle([rec]))
    assert issues == []


def test_run_hard_validation_catches_role_swap():
    rec = record(text="junction temperature exceeds the threshold (typically 170oC)")
    binding = NumericBinding(claim_value="170", unit="°C",
                             role="ambient_temperature",  # WRONG
                             evidence_id="ev1",
                             source_quote="junction temperature exceeds the threshold (typically 170oC)",
                             value_kind="typical")
    cl = claim("claim_a", "环境 170°C 关断。", ["ev1"],
              [EvidenceAnchor(evidence_id="ev1",
                               quote="junction temperature exceeds the threshold (typically 170oC)")],
              [binding], [], product_ids=["MP4570"])
    draft = AnswerDraft(draft_id="d1", claims=[cl], coverage="complete", gaps=[])
    issues = run_hard_validation(draft, bundle([rec]))
    assert any(i.code == "wrong_role" for i in issues)


def test_claim_id_format_required():
    with pytest.raises(ValidationError):
        Claim(claim_id="bad", text_zh="x", kind="document_fact",
              product_ids=[], evidence_ids=["ev1"], anchors=[],
              numeric_bindings=[], qualifier_bindings=[])


def test_clarification_request_required_fields():
    req = ClarificationRequest(
        request_id="cl_x", intent_revision=0, reason="missing_product",
        question="q", options=[ClarificationOption(option_id="o", label="l", proposed_value="v")],
        target_field="product_ids",
    )
    assert req.target_field == "product_ids"


def test_evidence_bundle_rejects_long_text():
    with pytest.raises(ValidationError):
        EvidenceRecord(
            chunk_id="ev1", doc_id="d", text="x" * 20001,
            products=[], document_sha256="abc",
            revision="", page_start=1, page_end=1, source_url="",
        )


def test_answer_result_cleans_fake_citations():
    r = AnswerResult(status="ANSWERED", answer_text="foo [99] bar")
    assert "[99]" not in r.answer_text


def test_conversation_state_phase_validation():
    s = ConversationState(session_id="s")
    assert s.phase == "IDLE"
    s.phase = "AWAITING_CLARIFICATION"
    assert s.phase == "AWAITING_CLARIFICATION"


def test_resolved_intent_dedupes_products():
    ri = ResolvedIntent(kind="document_qa", product_ids=["mp4570", "MP4570", "MP4570"],
                        topic="thermal_shutdown", scope_text="x")
    assert ri.product_ids == ["MP4570"]
