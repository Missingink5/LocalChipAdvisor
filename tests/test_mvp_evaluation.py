import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("evaluate_mvp", Path(__file__).parents[1] / "scripts/evaluate_mvp.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def record(text, page=1, sequence=1, digest="abc"):
    return {"text": text, "doc_id": "doc", "document_sha256": digest,
            "page_start": page, "page_end": page, "sequence": sequence}


def test_requires_complete_span_and_source_identity():
    span = {"verbatim_text": "start middle end", "source_sha256": "abc",
            "pdf_page_start": 1, "pdf_page_end": 1}
    assert not module.span_covered(span, [record("start middle")])
    assert module.span_covered(span, [record("start middle"), record("middle end", sequence=2)])
    assert not module.span_covered(span, [record("start middle end", digest="wrong")])
    assert not module.span_covered(span, [record("start middle end", page=2)])


def test_all_requirements_required():
    spans = {"one": {"verbatim_text": "one", "source_sha256": "abc", "pdf_page_start": 1, "pdf_page_end": 1},
             "two": {"verbatim_text": "two", "source_sha256": "abc", "pdf_page_start": 1, "pdf_page_end": 1}}
    case = {"gold_evidence_requirements": [
        {"requirement_id": "first", "alternative_span_ids": ["one"]},
        {"requirement_id": "second", "alternative_span_ids": ["two"]}]}
    assert not module.coverage(case, spans, [record("one")])["full_evidence"]
    assert module.coverage(case, spans, [record("one two")])["full_evidence"]
