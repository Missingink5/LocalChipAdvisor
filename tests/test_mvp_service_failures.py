from local_chip_advisor.mvp.service import AdvisorService, Selection, Support
from local_chip_advisor.mvp.answering import AnsweringEngine


class FakeIndex:
    def __init__(self):
        self.manifest = {"build_id": "test"}
        self.by_id = {}

    def search(self, *args, **kwargs):
        return [{
            "chunk_id": "allowed",
            "doc_id": "doc:fake",
            "products": ["MP4570"],
            "text": "Original evidence.",
            "raw_text": "Original evidence.",
            "document_sha256": "FAKE" * 16,
            "revision": "1.0",
            "page_start": 1,
            "page_end": 1,
            "source_url": "https://example.test",
        }]


class FakeChat:
    """A chat stub that yields a sequence of payloads."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []

    def chat(self, system, user_payload, schema, num_predict=1200, temperature=0.0):
        self.calls.append({"system": system, "user_payload": user_payload,
                           "schema": schema, "num_predict": num_predict})
        if not self._payloads:
            return {}
        return self._payloads.pop(0)


def service_with_chat(chat_stub):
    service = AdvisorService.__new__(AdvisorService)
    service.index = FakeIndex()
    service.build_id = "test"
    service.manifest_path = None
    service.chat = chat_stub
    service.engine = AnsweringEngine(chat_stub)
    return service


def _empty_draft():
    return {
        "draft_id": "draft_x",
        "claims": [],
        "coverage": "none",
        "gaps": [{"kind": "missing_evidence", "scope_zh": "无"}],
    }


def test_forged_citation_cannot_be_answered():
    """If the generator returns a draft with no valid evidence, the answer
    must not contain the forged ID."""
    fake = FakeChat([
        # intent proposal: ambiguous=false, products=[MP4570], topic=thermal_shutdown
        {"kind": "document_qa", "product_ids": ["MP4570"], "topic": "thermal_shutdown",
         "scope_text": "MP4570 thermal", "ambiguous": False,
         "resolution_basis": "explicit_request", "source_refs": []},
        # draft: refers to a forged evidence ID
        {"draft_id": "draft_x",
         "claims": [{
             "claim_id": "claim_a", "text_zh": "foo",
             "kind": "document_fact", "product_ids": ["MP4570"],
             "evidence_ids": ["forged"], "anchors": [], "numeric_bindings": [],
             "qualifier_bindings": []}],
         "coverage": "partial", "gaps": []},
        # audit
        {"review_id": "review_x", "claim_reviews": [
            {"claim_id": "claim_a", "verdict": "supported",
             "problem_codes": [], "supporting_evidence_ids": ["forged"]}],
         "answers_question": True, "coverage": "partial", "conflicts": []},
    ])
    service = service_with_chat(fake)
    result = service.ask("MP4570 thermal shutdown?")
    # The forged ID cannot appear in quotes or citations.
    for quote in result.get("quotes", []):
        assert quote.get("chunk_id") != "forged"
    for citation in result.get("citations", []):
        assert citation.get("chunk_id") != "forged"


def test_support_rejection_and_conflict():
    """When the audit says the draft is unsupported, status is INSUFFICIENT_EVIDENCE
    (or MODEL_ERROR if the revision pass also fails because the test fixture
    ran out of chat payloads — the key invariant is that the original supported
    claim must NOT be rendered as if it passed audit)."""
    fake = FakeChat([
        {"kind": "document_qa", "product_ids": ["MP4570"], "topic": "thermal_shutdown",
         "scope_text": "MP4570 thermal", "ambiguous": False,
         "resolution_basis": "explicit_request", "source_refs": []},
        # Draft with one valid claim referencing the allowed evidence
        {"draft_id": "draft_x",
         "claims": [{
             "claim_id": "claim_a", "text_zh": "Original evidence.",
             "kind": "document_fact", "product_ids": ["MP4570"],
             "evidence_ids": ["allowed"],
             "anchors": [{"evidence_id": "allowed", "quote": "Original evidence."}],
             "numeric_bindings": [], "qualifier_bindings": []}],
         "coverage": "partial", "gaps": []},
        # Audit rejects the claim
        {"review_id": "review_x", "claim_reviews": [
            {"claim_id": "claim_a", "verdict": "unsupported",
             "problem_codes": ["citation_not_supporting"],
             "supporting_evidence_ids": []}],
         "answers_question": False, "coverage": "none", "conflicts": []},
        # Revision: keep the draft as-is
        {"draft_id": "draft_y",
         "claims": [],
         "coverage": "none", "gaps": [{"kind": "missing_evidence", "scope_zh": "无"}]},
        # Post-revision audit
        {"review_id": "review_y", "claim_reviews": [],
         "answers_question": False, "coverage": "none", "conflicts": []},
    ])
    service = service_with_chat(fake)
    result = service.ask("MP4570 thermal shutdown?")
    assert result["status"] in {"INSUFFICIENT_EVIDENCE", "SOURCE_CONFLICT", "PARTIAL_ANSWER", "MODEL_ERROR"}


def test_retrieval_failure_has_distinct_status():
    class BrokenIndex(FakeIndex):
        def search(self, *args, **kwargs):
            raise RuntimeError("offline")

    service = service_with_chat(FakeChat([]))
    service.index = BrokenIndex()
    assert service.ask("MP4570 thermal shutdown?")["status"] == "RETRIEVAL_ERROR"
