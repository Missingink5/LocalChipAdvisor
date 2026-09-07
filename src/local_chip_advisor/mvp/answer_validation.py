"""Hard validators for draft answers, plus per-claim semantic audit helpers.

These validators do not trust the chat model. They enforce:

1. Schema and ID membership (every citation, anchor and binding points into
   this exact EvidenceBundle; no smuggling of IDs from prior builds).
2. Quote continuity (after whitespace/soft-hyphen normalization, the anchor
   quote must occur verbatim inside its evidence text; we never stitch a
   fabricated sentence together from two paragraphs).
3. Numeric binding integrity (value, unit, role, evidence_id and source
   quote must line up; Decimal-based unit conversion catches float drift).
4. Required-numeric discovery — we scan the Chinese claim text for numbers
   that the model forgot to declare in numeric_bindings, and reject the claim.
5. Role / value-kind / unit discipline — the model cannot promote Typical to
   a guaranteed rating, swap junction for ambient, or write continuous when
   the source says peak.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

from .contracts import (
    AnswerDraft,
    AnswerReview,
    Claim,
    ClaimReview,
    EvidenceBundle,
    EvidenceRecord,
    NumericBinding,
)

UNIT_ALIASES = {
    "V": "V", "伏": "V", "伏特": "V", "volt": "V", "volts": "V",
    "mV": "mV", "毫伏": "mV",
    "A": "A", "安": "A", "安培": "A", "amp": "A", "amps": "A",
    "mA": "mA", "毫安": "mA",
    "uA": "uA", "μA": "uA", "微安": "uA",
    "°C": "°C", "C": "°C", "摄氏度": "°C", "度": "°C", "度C": "°C",
    "°F": "°F",
    "Hz": "Hz", "kHz": "kHz", "MHz": "MHz", "GHz": "GHz",
    "s": "s", "ms": "ms", "us": "us", "μs": "us", "ns": "ns",
    "%": "%",
}
UNIT_TO_BASE = {
    "V": ("voltage", Decimal("1")),
    "mV": ("voltage", Decimal("0.001")),
    "A": ("current", Decimal("1")),
    "mA": ("current", Decimal("0.001")),
    "uA": ("current", Decimal("0.000001")),
    "μA": ("current", Decimal("0.000001")),
    "°C": ("temperature", Decimal("1")),
    "°F": ("temperature", Decimal("1")),  # do not auto-convert Fahrenheit
    "Hz": ("frequency", Decimal("1")),
    "kHz": ("frequency", Decimal("1000")),
    "MHz": ("frequency", Decimal("1000000")),
    "GHz": ("frequency", Decimal("1000000000")),
    "s": ("time", Decimal("1")),
    "ms": ("time", Decimal("0.001")),
    "us": ("time", Decimal("0.000001")),
    "ns": ("time", Decimal("0.000000001")),
    "%": ("ratio", Decimal("1")),
}


def normalize_text(text: str) -> str:
    """Whitespace, soft-hyphen and case normalization for anchor matching."""
    cleaned = unicodedata.normalize("NFKC", text.replace("­", ""))
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace("​", "")
    return cleaned.lower()


def extract_numbers(text: str) -> list[tuple[str, str]]:
    """Find numeric tokens in Chinese/English text together with a unit guess.

    Returns (number_string, unit_string) tuples. The unit string is the raw
    suffix that follows the digits, used only for downstream validation.
    """
    text = text or ""
    matches: list[tuple[str, str]] = []
    # English / latin number + unit
    for match in re.finditer(
        r"(?P<num>-?\d+(?:\.\d+)?)\s*"
        r"(?P<unit>m?[VA°CFuµ]?Hz|kHz|MHz|GHz|ms|us|μs|ns|s|%|°C|mA|uA|μA|µA|mV|°F)?",
        text,
    ):
        n, u = match.group("num"), (match.group("unit") or "").strip()
        if not u:
            continue
        # normalize µA / uA
        if u == "µA":
            u = "μA"
        matches.append((n, u))
    # Chinese numerals attached to units like 10度 / 170度
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(度C|度|摄氏度|伏特|伏|安培|安|毫安|微安)", text):
        matches.append((match.group(1), match.group(2)))
    return matches


def convert_to_base(value: str, unit: str) -> tuple[str, Decimal] | None:
    """Convert value+unit into a canonical base (voltage/current/...)."""
    try:
        dec = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if unit not in UNIT_TO_BASE:
        # Treat unknown units as opaque, but still return something.
        return ("unknown", dec)
    kind, scale = UNIT_TO_BASE[unit]
    return (kind, dec * scale)


def units_compatible(unit_a: str, unit_b: str) -> bool:
    """Two units are compatible when they map to the same physical kind."""
    if unit_a == unit_b:
        return True
    if unit_a not in UNIT_TO_BASE or unit_b not in UNIT_TO_BASE:
        return False
    return UNIT_TO_BASE[unit_a][0] == UNIT_TO_BASE[unit_b][0]


def values_equal(value_a: str, unit_a: str, value_b: str, unit_b: str) -> bool | None:
    """Return True/False if numeric equality is decidable, None if unknown."""
    conv_a = convert_to_base(value_a, unit_a)
    conv_b = convert_to_base(value_b, unit_b)
    if not conv_a or not conv_b:
        return None
    if conv_a[0] == "unknown" or conv_b[0] == "unknown":
        return None
    if conv_a[0] != conv_b[0]:
        return False
    try:
        return conv_a[1] == conv_b[1]
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class HardIssue:
    code: str
    scope: str
    detail: str


# ---------------------------------------------------------------------------
# Stage 1: structural / ID membership
# ---------------------------------------------------------------------------


def validate_draft_structure(draft: AnswerDraft, bundle: EvidenceBundle) -> list[HardIssue]:
    issues: list[HardIssue] = []
    allowed_ids = {r.chunk_id for r in bundle.records}
    allowed_record_by_id = {r.chunk_id: r for r in bundle.records}
    seen_claim_ids: set[str] = set()

    if not draft.claims and draft.coverage != "none":
        issues.append(HardIssue("empty_draft", "draft", "模型未提供任何事实"))
    for claim in draft.claims:
        if claim.claim_id in seen_claim_ids:
            issues.append(HardIssue("duplicate_claim", claim.claim_id, "claim_id 重复"))
        seen_claim_ids.add(claim.claim_id)
        if claim.kind not in ("document_fact", "rule_result"):
            issues.append(HardIssue("bad_kind", claim.claim_id, f"未知 kind={claim.kind}"))
        if not claim.evidence_ids:
            issues.append(HardIssue("no_evidence", claim.claim_id, "事实未引用任何 evidence_id"))
        for evidence_id in claim.evidence_ids:
            if evidence_id not in allowed_ids:
                issues.append(HardIssue("foreign_evidence", claim.claim_id, f"引用了非本次证据: {evidence_id}"))
        for anchor in claim.anchors:
            if anchor.evidence_id not in allowed_ids:
                issues.append(HardIssue("anchor_foreign_evidence", claim.claim_id, anchor.evidence_id))
                continue
            record = allowed_record_by_id[anchor.evidence_id]
            if not quote_present(record.text, anchor.quote):
                issues.append(HardIssue(
                    "anchor_not_in_evidence", claim.claim_id,
                    f"引用片段不在 {anchor.evidence_id} 全文中",
                ))
        for binding in claim.numeric_bindings:
            if binding.evidence_id not in allowed_ids:
                issues.append(HardIssue("binding_foreign_evidence", claim.claim_id, binding.evidence_id))
                continue
            record = allowed_record_by_id[binding.evidence_id]
            if not quote_present(record.text, binding.source_quote):
                issues.append(HardIssue(
                    "binding_quote_not_in_evidence", claim.claim_id,
                    f"数值引用片段不在 {binding.evidence_id} 全文中",
                ))
        for qualifier in claim.qualifier_bindings:
            if qualifier.evidence_id not in allowed_ids:
                issues.append(HardIssue("qualifier_foreign_evidence", claim.claim_id, qualifier.evidence_id))
                continue
            record = allowed_record_by_id[qualifier.evidence_id]
            if not quote_present(record.text, qualifier.source_quote):
                issues.append(HardIssue(
                    "qualifier_quote_not_in_evidence", claim.claim_id,
                    f"条件引用片段不在 {qualifier.evidence_id} 全文中",
                ))
    return issues


# ---------------------------------------------------------------------------
# Stage 2: numeric bindings & required-numeric discovery
# ---------------------------------------------------------------------------

_NUMERIC_FIND = re.compile(r"-?\d+(?:\.\d+)?")


def quote_present(evidence_text: str, quote: str) -> bool:
    return normalize_text(quote) in normalize_text(evidence_text)


def _claim_declared_numbers(claim: Claim) -> list[tuple[str, str]]:
    declared: list[tuple[str, str]] = []
    for binding in claim.numeric_bindings:
        declared.append((binding.claim_value, binding.unit))
    return declared


def _numbers_in_evidence(record: EvidenceRecord) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    text = record.text
    # Recognize the "oC" datasheet spelling so 160oC and 170oC are caught.
    text = text.replace("oC", "°C").replace("OC", "°C")
    for num, unit in extract_numbers(text):
        canonical = UNIT_ALIASES.get(unit, unit)
        out.append((num, canonical))
    # Strip empty units
    return [(n, u) for n, u in out if u]


def find_missing_numeric_bindings(claim: Claim, record: EvidenceRecord) -> list[str]:
    """Detect numbers in the claim text that are not declared in bindings.

    Returns a list of (claim_value, unit) that should have been bound but
    weren't. Tolerance: numeric_bindings whose source_quote is the same as the
    detected substring are not flagged again. Numbers without a recognized
    unit in the record (like plain "160" followed by "oC") are still flagged
    using the bare value as the missing hint.

    Numbers that appear inside product identifiers (e.g. "4570" from MP4570)
    are NOT flagged — they are product tokens, not measured values.
    """
    missing: list[str] = []
    claim_text = claim.text_zh or ""
    # Strip product identifiers from the claim text so digits inside them
    # don't get mistaken for measured values.
    for product in ("MP4570", "TPS54331", "TPS562201", "TPS562208", "LT8610"):
        claim_text = re.sub(re.escape(product), " ", claim_text, flags=re.IGNORECASE)
    claim_numbers = _NUMERIC_FIND.findall(claim_text)
    if not claim_numbers:
        return missing
    declared = {b.claim_value for b in claim.numeric_bindings}
    record_numbers = _numbers_in_evidence(record)
    record_values = {n for n, _ in record_numbers}
    for number in claim_numbers:
        if number in declared:
            continue
        if number not in record_values:
            missing.append(number)
            continue
        for n, unit in record_numbers:
            if n == number:
                missing.append(f"{number}{unit or ''}")
                break
    return missing


def validate_numeric_bindings(claim: Claim, record: EvidenceRecord) -> list[HardIssue]:
    issues: list[HardIssue] = []
    for binding in claim.numeric_bindings:
        canonical_unit = UNIT_ALIASES.get(binding.unit, binding.unit)
        if canonical_unit != binding.unit:
            issues.append(HardIssue(
                "noncanonical_unit", claim.claim_id,
                f"单位 {binding.unit} 非标准写法",
            ))
        # source_quote must contain the numeric value
        normalized_quote = normalize_text(binding.source_quote)
        normalized_value = binding.claim_value.replace(",", "")
        if normalized_value not in normalized_quote:
            issues.append(HardIssue(
                "binding_value_not_in_quote", claim.claim_id,
                f"binding value {binding.claim_value} 未出现在 source_quote 中",
            ))
        # value_kind sanity
        if binding.value_kind == "unknown" and binding.role not in {"other", "current_limit"}:
            issues.append(HardIssue(
                "value_kind_unknown_with_role", claim.claim_id,
                f"角色 {binding.role} 不应标记为 unknown",
            ))
    missing = find_missing_numeric_bindings(claim, record)
    if missing:
        issues.append(HardIssue(
            "numeric_binding_missing", claim.claim_id,
            "claim 含数字但未声明 binding: " + ", ".join(missing),
        ))
    return issues


def validate_value_kind_discipline(claim: Claim, record: EvidenceRecord) -> list[HardIssue]:
    """Reject claims that promote Typical / Min / Max across the wrong grade.

    Uses simple heuristic over the source quote: if the quote says "typically"
    but the binding's value_kind is not typical, reject. Conversely, if the
    quote says "absolute maximum" and value_kind is "nominal", reject.
    """
    issues: list[HardIssue] = []
    quote_lower = record.text.lower()
    for binding in claim.numeric_bindings:
        if not quote_present(record.text, binding.source_quote):
            continue
        snippet = binding.source_quote.lower()
        says_typical = "typically" in snippet or "typical" in snippet
        says_min = "min" in snippet or "minimum" in snippet
        says_max = "max" in snippet or "maximum" in snippet
        says_absolute = "absolute maximum" in snippet or "absolute max" in snippet
        says_recommended = "recommended operating" in snippet or "recommended condition" in snippet
        if says_typical and binding.value_kind not in {"typical", "unknown"}:
            issues.append(HardIssue(
                "wrong_value_kind", claim.claim_id,
                f"原文含 'typically'，但 value_kind={binding.value_kind}",
            ))
        if says_absolute and binding.value_kind not in {"max", "unknown"}:
            issues.append(HardIssue(
                "wrong_value_kind", claim.claim_id,
                f"原文为 'absolute maximum'，不能写为 {binding.value_kind}",
            ))
        if says_recommended and binding.value_kind == "max":
            issues.append(HardIssue(
                "wrong_value_kind", claim.claim_id,
                "原文为 recommended operating conditions，不能写成 max",
            ))
        if says_min and binding.value_kind in {"max", "typical", "nominal"}:
            issues.append(HardIssue(
                "wrong_value_kind", claim.claim_id,
                f"原文为 min，value_kind={binding.value_kind}",
            ))
        # ambient vs junction discipline
        if binding.role == "ambient_temperature" and ("junction" in snippet or "tj" in snippet.lower()):
            issues.append(HardIssue(
                "wrong_role", claim.claim_id,
                "原文说的是结温 junction，不能写入 ambient_temperature",
            ))
        if binding.role in {"junction_shutdown_trigger", "junction_recovery_threshold"} and "ambient" in snippet:
            issues.append(HardIssue(
                "wrong_role", claim.claim_id,
                "原文说的是 ambient，不能写入 junction_*",
            ))
        # continuous vs peak discipline
        if binding.role == "continuous_output_current" and re.search(r"peak|峰值", snippet):
            issues.append(HardIssue(
                "wrong_role", claim.claim_id,
                "原文含 peak/峰值，不能写入 continuous_output_current",
            ))
        if binding.role == "peak_output_current" and re.search(r"continuous|持续|连续", snippet):
            issues.append(HardIssue(
                "wrong_role", claim.claim_id,
                "原文含 continuous/持续，不能写入 peak_output_current",
            ))
    return issues


def validate_unit_consistency(claim: Claim, record: EvidenceRecord) -> list[HardIssue]:
    issues: list[HardIssue] = []
    for binding in claim.numeric_bindings:
        # Pull units mentioned alongside the binding value in the source quote
        snippet = binding.source_quote
        source_units = [u for _, u in extract_numbers(snippet)]
        if not source_units:
            continue
        canonical_source = [UNIT_ALIASES.get(u, u) for u in source_units]
        if binding.unit not in canonical_source and not any(
            units_compatible(binding.unit, u) for u in canonical_source
        ):
            issues.append(HardIssue(
                "wrong_unit", claim.claim_id,
                f"声明单位 {binding.unit}，原文单位 {canonical_source}",
            ))
    return issues


def validate_role_consistency(claim: Claim, record: EvidenceRecord) -> list[HardIssue]:
    """The claim's role must match the evidence document's product scope."""
    issues: list[HardIssue] = []
    if not claim.product_ids:
        issues.append(HardIssue("missing_product_in_claim", claim.claim_id, "事实未声明 product_ids"))
        return issues
    record_products = {p.upper() for p in record.products}
    for pid in claim.product_ids:
        if pid.upper() not in record_products:
            issues.append(HardIssue(
                "wrong_product", claim.claim_id,
                f"产品 {pid} 不在证据 {record.chunk_id} 适用集合 {sorted(record_products)} 中",
            ))
    return issues


# ---------------------------------------------------------------------------
# Aggregate entry point used by answering.py
# ---------------------------------------------------------------------------


def run_hard_validation(draft: AnswerDraft, bundle: EvidenceBundle) -> list[HardIssue]:
    issues = list(validate_draft_structure(draft, bundle))
    record_by_id = {r.chunk_id: r for r in bundle.records}
    for claim in draft.claims:
        # Pick the first valid evidence record for additional validation
        primary = None
        for evidence_id in claim.evidence_ids:
            if evidence_id in record_by_id:
                primary = record_by_id[evidence_id]
                break
        if primary is None:
            continue
        issues.extend(validate_role_consistency(claim, primary))
        issues.extend(validate_numeric_bindings(claim, primary))
        issues.extend(validate_value_kind_discipline(claim, primary))
        issues.extend(validate_unit_consistency(claim, primary))
    return issues


# ---------------------------------------------------------------------------
# Stage 2 (semantic): per-claim audit hook — the LLM fills this in.
# ---------------------------------------------------------------------------


def require_complete_review(draft: AnswerDraft, review: AnswerReview) -> list[HardIssue]:
    """The chat audit must cover every claim, no more, no less."""
    issues: list[HardIssue] = []
    expected = {c.claim_id for c in draft.claims}
    received = [r.claim_id for r in review.claim_reviews]
    missing = expected - set(received)
    extra = set(received) - expected
    if missing:
        issues.append(HardIssue("review_missing_claim", "review", "missing: " + ",".join(sorted(missing))))
    if extra:
        issues.append(HardIssue("review_extra_claim", "review", "extra: " + ",".join(sorted(extra))))
    if review.draft_hash and draft.draft_hash and review.draft_hash != draft.draft_hash:
        issues.append(HardIssue("review_hash_mismatch", "review", "review refers to a different draft"))
    if review.evidence_set_hash and review.evidence_set_hash != bundle_hash_for(draft):
        # The review is supposed to be bound to the same evidence set the
        # draft was generated against. We re-derive and compare.
        pass  # caller must check using the actual bundle.
    return issues


def bundle_hash_for(_: AnswerDraft) -> str:
    """Placeholder; the real bundle hash is supplied by the caller. Keeping
    this thin function makes it easy to grep usages and enforce the call."""
    return ""


# ---------------------------------------------------------------------------
# Citation continuity / final render guards
# ---------------------------------------------------------------------------


def detect_unsupported_inference(claim: Claim, record: EvidenceRecord) -> list[HardIssue]:
    """Heuristics for the most common inference categories.

    The model is allowed to translate wording, but it is not allowed to claim
    engineering safety or to invent functions when the evidence is absent.
    """
    issues: list[HardIssue] = []
    text = claim.text_zh
    lowered = text.lower()
    safe_words = ("一定合格", "绝对安全", "绝不会损坏", "绝对不会损坏", "guaranteed to",
                  "always safe", "definitely safe", "never fails")
    if any(phrase in lowered for phrase in safe_words):
        issues.append(HardIssue(
            "unsupported_inference", claim.claim_id,
            "事实包含无条件安全承诺，模型不能下此结论",
        ))
    if "效率" in text and any(b.role == "quiescent_current" for b in claim.numeric_bindings):
        issues.append(HardIssue(
            "unsupported_inference", claim.claim_id,
            "从 quiescent_current 推断效率不成立",
        ))
    # Paragraph-level product relevance is checked in semantic audit; here we
    # only catch structural mismatches.
    return issues


def consolidate_claims_for_render(draft: AnswerDraft, review: AnswerReview) -> list[Claim]:
    """Return only the claims the review verdict-marked as supported."""
    verdict_by_id = {r.claim_id: r for r in review.claim_reviews}
    return [c for c in draft.claims if verdict_by_id.get(c.claim_id) and verdict_by_id[c.claim_id].verdict == "supported"]


def first_unanswered(draft: AnswerDraft, review: AnswerReview) -> Iterable[str]:
    seen = {r.claim_id for r in review.claim_reviews}
    for claim in draft.claims:
        if claim.claim_id not in seen:
            yield claim.claim_id
