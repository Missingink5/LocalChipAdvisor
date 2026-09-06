"""Deterministic structural validator for the S04 gold evaluation dataset.

Scope: evaluations/corpus_manifest.json + evaluations/cases/*.jsonl.

Hard rules enforced here (see evaluations/cases/annotation_guide.md):

- every file is clean UTF-8 JSON/JSONL (LF endings, no BOM, no trailing
  whitespace, every line is one object, one trailing newline);
- the corpus manifest resolves: every document's local_file exists on disk and
  its sha256 matches the recorded one (offline hashing only);
- gold spans bind to documents by source_id + sha256 + 1-based PDF page range;
  no chunk_id field exists anywhere (chunk mapping is S05/S07 work);
- case records reference only existing spans, only for products the case is
  about (span.product_ids subset of allowed_product_ids);
- a semantic group never crosses split: group ids are disjoint across
  dev/holdout and across normal/boundary files;
- normal semantic groups carry exactly the four language expressions;
- the first ten semantic groups are permanently dev (locked id constant);
- human_reviewed is false everywhere until the user explicitly approves.

Final-count assertions (50 groups / 200 cases / 40 boundary cases, 30/20 split)
are gated on evaluations/cases/dataset_manifest.json, which is only created at
S04.13. Before that, the structural invariants above must already be green.

Unlock procedure after the user's S04.12 review: replace the
human_reviewed-is-false assertions with the reviewed inventory recorded in the
review record (a reviewed case/span id must appear there); the same applies to
holdout_sealed, which stays false until the user explicitly approves sealing.

This test performs no network, model, Chroma, or embedding calls.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "evaluations"
CASES_DIR = EVAL_DIR / "cases"
MANIFEST_PATH = EVAL_DIR / "corpus_manifest.json"
DATASET_MANIFEST_PATH = CASES_DIR / "dataset_manifest.json"
SEMANTIC_SCOPE_REVIEW_PATH = CASES_DIR / "semantic_scope_review.json"

CASE_FILES = {
    "dev": CASES_DIR / "dev.jsonl",
    "holdout": CASES_DIR / "holdout.jsonl",
    "boundary_dev": CASES_DIR / "boundary_dev.jsonl",
    "boundary_holdout": CASES_DIR / "boundary_holdout.jsonl",
}
FILE_SPLIT = {
    "dev": "dev",
    "holdout": "holdout",
    "boundary_dev": "dev",
    "boundary_holdout": "holdout",
}
SPAN_FILE = CASES_DIR / "gold_spans.jsonl"

LANGUAGE_GROUPS = {"zh_formal", "zh_colloquial", "en", "zh_en_mixed"}
STATUSES = {"ANSWERED", "NEEDS_CLARIFICATION", "INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE"}

CASE_FIELDS = {
    "case_id",
    "semantic_group_id",
    "split",
    "query",
    "language_group",
    "session_context",
    "expected_intents",
    "expected_status",
    "allowed_product_ids",
    "gold_evidence_requirements",
    "required_qualifiers",
    "forbidden_claims",
    "human_reviewed",
}
SPAN_FIELDS = {
    "span_id",
    "source_id",
    "product_ids",
    "source_sha256",
    "pdf_page_start",
    "pdf_page_end",
    "section",
    "verbatim_text",
    "required_qualifiers",
    "human_reviewed",
}

# S04.6 authors these ten groups first; the guide locks them to dev forever.
FIRST_TEN_DEV_GROUP_IDS = (
    "mp4570.thermal_shutdown.01",
    "mp4570.soft_start.01",
    "mp4570.input_range.01",
    "mp4570.ovp.01",
    "mp4570.uvlo.01",
    "tps54331.soft_start.01",
    "tps54331.light_load.01",
    "tps562201.soft_start.01",
    "lt8610.quiescent.01",
    "tps54331.thermal_shutdown.01",
)

NO_CHANGE_SCOPE_GROUP_IDS = frozenset(
    {
        "lt8610.frequency.01",
        "mp4570.output_set.01",
        "mp4570.power_good.01",
        "mp4570.uvlo.01",
        "tps54331.frequency.01",
        "tps54331.vout_set.01",
        "tps562201.ocl.01",
        "tps562201.uvlo.01",
        "tps562201.uvp.01",
    }
)
CORRECTED_SCOPE_GROUP_IDS = frozenset(
    {
        "lt8610.burst.01",
        "lt8610.en_uv.01",
        "lt8610.foldback.01",
        "lt8610.ilim.01",
        "lt8610.pg.01",
        "lt8610.quiescent.01",
        "lt8610.sync.01",
        "lt8610.thermal_resistance.01",
        "lt8610.trss.01",
        "mp4570.bias.01",
        "mp4570.bootstrap.01",
        "mp4570.en_zener.01",
        "mp4570.input_range.01",
        "mp4570.light_load.01",
        "mp4570.ocp.01",
        "mp4570.output_range.01",
        "mp4570.ovp.01",
        "mp4570.soft_start.01",
        "mp4570.sync.01",
        "mp4570.thermal_resistance.01",
        "mp4570.thermal_shutdown.01",
        "tps54331.boot.01",
        "tps54331.emc.01",
        "tps54331.en.01",
        "tps54331.iq.01",
        "tps54331.layout.01",
        "tps54331.light_load.01",
        "tps54331.ocp.01",
        "tps54331.ovtp.01",
        "tps54331.soft_start.01",
        "tps54331.thermal_shutdown.01",
        "tps54331.vref.01",
        "tps562201.eco.01",
        "tps562201.eco_fccm.01",
        "tps562201.frequency.01",
        "tps562201.input_range.01",
        "tps562201.layout.01",
        "tps562201.shutdown_current.01",
        "tps562201.soft_start.01",
        "tps562201.tsd.01",
        "tps562201.vfb_accuracy.01",
    }
)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name}: BOM not allowed"
    text = raw.decode("utf-8")
    assert "\r" not in text, f"{path.name}: CR not allowed (use LF)"
    assert "\t" not in text, f"{path.name}: tab characters not allowed"
    if not text:
        return []
    assert text.endswith("\n"), f"{path.name}: must end with a single newline"
    records: list[dict[str, object]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        assert line == line.rstrip(), f"{path.name}:{line_no}: trailing whitespace"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion failure path
            raise AssertionError(f"{path.name}:{line_no}: invalid JSON: {exc}") from exc
        assert isinstance(obj, dict), f"{path.name}:{line_no}: not a JSON object"
        records.append(obj)
    return records


def _read_manifest() -> dict[str, object]:
    assert MANIFEST_PATH.is_file(), "evaluations/corpus_manifest.json missing"
    raw = MANIFEST_PATH.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "corpus_manifest.json: BOM not allowed"
    obj = json.loads(raw.decode("utf-8"))
    assert isinstance(obj, dict), "corpus_manifest.json: not a JSON object"
    return obj


def _load_all() -> tuple[
    dict[str, object],
    list[dict[str, object]],
    dict[str, list[dict[str, object]]],
]:
    manifest = _read_manifest()
    spans = _read_jsonl(SPAN_FILE)
    cases = {name: _read_jsonl(path) for name, path in CASE_FILES.items()}
    return manifest, spans, cases


def _documents(manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    docs = manifest["documents"]
    assert isinstance(docs, list) and docs, "corpus_manifest.json: documents missing"
    by_id: dict[str, dict[str, object]] = {}
    for doc in docs:
        assert isinstance(doc, dict), "corpus_manifest.json: document not an object"
        source_id = doc.get("source_id")
        assert isinstance(source_id, str) and source_id, "document lacks source_id"
        assert source_id not in by_id, f"duplicate source_id {source_id}"
        by_id[source_id] = doc
    return by_id


def _products_of(doc: dict[str, object]) -> set[str]:
    products = doc.get("product_ids")
    assert isinstance(products, list) and products, "document lacks product_ids"
    return {p for p in products if isinstance(p, str) and p}


def _span_ids_by_case(cases: list[dict[str, object]]) -> set[str]:
    used: set[str] = set()
    for case in cases:
        for req in case["gold_evidence_requirements"]:
            used.update(req["alternative_span_ids"])
    return used


def _has_dataset_manifest() -> bool:
    return DATASET_MANIFEST_PATH.is_file()


def _read_dataset_manifest() -> dict[str, object] | None:
    if not _has_dataset_manifest():
        return None
    obj = json.loads(DATASET_MANIFEST_PATH.read_bytes().decode("utf-8"))
    assert isinstance(obj, dict), "dataset_manifest.json: not a JSON object"
    return obj


def _normalize_pdf_verbatim(text: str) -> str:
    """Normalize only the documented PDF soft-hyphen extraction artifact."""

    text = re.sub("\u00ad[ \t]*\r?\n[ \t]*", "", text)
    text = text.replace("\u00ad", "")
    lines = (line.strip() for line in text.splitlines())
    return " ".join(line for line in lines if line)


# ---------------------------------------------------------------- files


def test_s04_files_exist_and_are_wellformed_jsonl() -> None:
    """Manifest and all five case/span files exist and parse as clean JSONL."""

    assert EVAL_DIR.is_dir()
    for path in [MANIFEST_PATH, SPAN_FILE, *CASE_FILES.values()]:
        assert path.is_file(), f"missing {path.relative_to(REPO_ROOT)}"
    # parse everything; _read_jsonl/_read_manifest raise on hygiene violations
    manifest, spans, cases = _load_all()
    assert isinstance(manifest["documents"], list)
    assert isinstance(spans, list)
    for records in cases.values():
        assert isinstance(records, list)


# ---------------------------------------------------------------- manifest


def test_s04_corpus_manifest_hashes_resolve_to_local_pdfs() -> None:
    """Every recorded document exists on disk and its sha256 matches exactly."""

    manifest = _read_manifest()
    assert manifest.get("schema_version") == 1, "schema_version must be 1"
    assert manifest.get("corpus_id") == "s04-corpus-v1"
    for doc in _documents(manifest).values():
        sha = doc.get("sha256")
        assert isinstance(sha, str) and len(sha) == 64, "sha256 must be 64 chars"
        assert sha == sha.upper(), "sha256 must be uppercase hex"
        assert int(sha, 16) >= 0  # raises on non-hex
        pages = doc.get("pdf_pages")
        assert isinstance(pages, int) and pages >= 1, "pdf_pages must be >= 1"
        local_file = doc.get("local_file")
        assert isinstance(local_file, str) and local_file
        path = REPO_ROOT / local_file
        assert path.is_file(), f"corpus file missing on disk: {local_file}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        assert actual == sha, f"sha256 mismatch for {local_file}"
        reviewed = doc.get("human_reviewed")
        assert reviewed is False, f"{doc['source_id']}: human_reviewed must stay false"


# ---------------------------------------------------------------- spans


def test_s04_gold_spans_contract() -> None:
    """Span fields, uniqueness, document binding, page bounds, no chunk_id."""

    manifest = _read_manifest()
    docs = _documents(manifest)
    spans = _read_jsonl(SPAN_FILE)
    seen: set[str] = set()
    for span in spans:
        assert set(span) == SPAN_FIELDS, f"span field set mismatch: {span.get('span_id')}"
        span_id = span["span_id"]
        assert isinstance(span_id, str) and span_id and span_id not in seen
        seen.add(span_id)
        source = docs.get(span["source_id"])
        assert source is not None, f"{span_id}: unknown source_id"
        assert (
            span["source_sha256"] == source["sha256"]
        ), f"{span_id}: sha256 does not match manifest"
        assert span["product_ids"], f"{span_id}: product_ids empty"
        products = {p for p in span["product_ids"] if isinstance(p, str) and p}
        assert products <= _products_of(source), f"{span_id}: product not in document"
        start, end = span["pdf_page_start"], span["pdf_page_end"]
        assert isinstance(start, int) and isinstance(end, int)
        assert 1 <= start <= end <= source["pdf_pages"], f"{span_id}: page range bad"
        text = span["verbatim_text"]
        assert isinstance(text, str) and text, f"{span_id}: empty verbatim_text"
        assert text == text.strip(), f"{span_id}: verbatim_text has edge whitespace"
        assert len(text) <= 400, f"{span_id}: verbatim_text too long"
        assert isinstance(span["section"], str) and span["section"]
        assert isinstance(span["required_qualifiers"], list)
        assert span["human_reviewed"] is False, f"{span_id}: human_reviewed must be false"


def test_s04_gold_spans_are_verbatim_on_declared_physical_pages() -> None:
    """Every gold quote must occur within its declared physical PDF pages."""

    manifest = _read_manifest()
    sources = _documents(manifest)
    spans = _read_jsonl(SPAN_FILE)
    open_documents: dict[str, pymupdf.Document] = {}
    page_text_cache: dict[tuple[str, int], str] = {}

    try:
        for source_id, source in sources.items():
            local_file = source.get("local_file")
            expected_pages = source.get("pdf_pages")
            assert isinstance(local_file, str) and local_file
            assert isinstance(expected_pages, int)
            document = pymupdf.open(REPO_ROOT / local_file)
            open_documents[source_id] = document
            assert document.page_count == expected_pages, (
                f"{source_id}: PDF page_count={document.page_count}, "
                f"manifest pdf_pages={expected_pages}"
            )

        for span in spans:
            span_id = span["span_id"]
            source_id = span["source_id"]
            start = span["pdf_page_start"]
            end = span["pdf_page_end"]
            needle = span["verbatim_text"]
            assert isinstance(span_id, str)
            assert isinstance(source_id, str)
            assert isinstance(start, int) and isinstance(end, int)
            assert isinstance(needle, str)

            document = open_documents[source_id]
            declared_page_text: list[str] = []
            for physical_page in range(start, end + 1):
                cache_key = (source_id, physical_page)
                if cache_key not in page_text_cache:
                    page_text_cache[cache_key] = document[physical_page - 1].get_text()
                declared_page_text.append(page_text_cache[cache_key])

            haystack = _normalize_pdf_verbatim("\n".join(declared_page_text))
            normalized_needle = _normalize_pdf_verbatim(needle)
            assert normalized_needle in haystack, (
                f"{span_id}: verbatim text not found in {source_id} "
                f"physical pages {start}..{end}"
            )
    finally:
        for document in open_documents.values():
            document.close()


# ---------------------------------------------------------------- cases


def test_s04_case_records_contract_and_split_consistency() -> None:
    """Case field sets, split matches its file, and ids are globally unique."""

    _, spans, cases = _load_all()
    seen: set[str] = set()
    for name, records in cases.items():
        expected_split = FILE_SPLIT[name]
        for case in records:
            assert set(case) == CASE_FIELDS, f"case field mismatch: {case.get('case_id')}"
            case_id = case["case_id"]
            assert isinstance(case_id, str) and case_id and case_id not in seen
            seen.add(case_id)
            assert case["split"] == expected_split, f"{case_id}: split/file mismatch"
            assert case["semantic_group_id"], f"{case_id}: empty semantic_group_id"
            assert case["language_group"] in LANGUAGE_GROUPS, case_id
            assert case["expected_status"] in STATUSES, case_id
            context = case["session_context"]
            assert set(context) == {"explicit_product_ids"}, case_id
            assert isinstance(context["explicit_product_ids"], list), case_id
            intents = case["expected_intents"]
            assert isinstance(intents, list) and intents, case_id
            if case["expected_status"] != "OUT_OF_SCOPE":
                assert "document_qa" in intents, case_id
            allowed = {p for p in case["allowed_product_ids"] if isinstance(p, str) and p}
            if case["expected_status"] == "ANSWERED":
                assert allowed, f"{case_id}: allowed_product_ids empty"
            assert isinstance(case["required_qualifiers"], list), case_id
            assert isinstance(case["forbidden_claims"], list), case_id
            assert case["human_reviewed"] is False, f"{case_id}: human_reviewed must be false"
            # evidence requirements point at spans, one requirement id each
            req_ids: set[str] = set()
            for req in case["gold_evidence_requirements"]:
                assert set(req) == {"requirement_id", "alternative_span_ids"}, case_id
                assert req["requirement_id"] and req["requirement_id"] not in req_ids
                req_ids.add(req["requirement_id"])
                alts = req["alternative_span_ids"]
                assert isinstance(alts, list) and alts, f"{case_id}: empty alternative set"
                for span_id in alts:
                    assert span_id in {s["span_id"] for s in spans}, (
                        f"{case_id}: references missing span {span_id}"
                    )
            span_index = {s["span_id"]: s for s in spans}
            for req in case["gold_evidence_requirements"]:
                for span_id in req["alternative_span_ids"]:
                    span_products = {p for p in span_index[span_id]["product_ids"]}
                    assert span_products <= allowed, (
                        f"{case_id}: span {span_id} covers products outside allowed set"
                    )
            if case["expected_status"] == "ANSWERED":
                assert case["gold_evidence_requirements"], (
                    f"{case_id}: ANSWERED case needs evidence requirements"
                )


def test_s04_semantic_groups_never_cross_split() -> None:
    """Group ids are disjoint across normal/boundary and dev/holdout."""

    _, _, cases = _load_all()
    group_split: dict[str, str] = {}
    group_kind: dict[str, str] = {}
    for name, records in cases.items():
        kind = "boundary" if name.startswith("boundary_") else "normal"
        split = FILE_SPLIT[name]
        for case in records:
            gid = case["semantic_group_id"]
            if gid in group_split:
                assert group_split[gid] == split, f"{gid}: group crosses split"
                assert group_kind[gid] == kind, f"{gid}: group crosses normal/boundary"
            else:
                group_split[gid] = split
                group_kind[gid] = kind


def test_s04_normal_groups_have_all_four_language_expressions() -> None:
    """Every normal semantic group carries exactly the four expressions."""

    _, _, cases = _load_all()
    for name, records in cases.items():
        if name.startswith("boundary_"):
            continue
        groups: dict[str, set[str]] = {}
        for case in records:
            groups.setdefault(case["semantic_group_id"], set()).add(case["language_group"])
        for gid, langs in groups.items():
            assert langs == LANGUAGE_GROUPS, f"{gid}: incomplete language expressions"


def test_s04_semantic_scope_technical_pre_review_inventory() -> None:
    """Technical scope review covers every normal group without human approval."""

    assert SEMANTIC_SCOPE_REVIEW_PATH.is_file(), "semantic scope review missing"
    review = json.loads(SEMANTIC_SCOPE_REVIEW_PATH.read_text(encoding="utf-8"))
    assert review["review_kind"] == "technical_pre_review"
    assert review["human_reviewed"] is False
    entries = review["groups"]
    assert isinstance(entries, list)
    assert all(
        set(entry)
        == {"semantic_group_id", "disposition", "scope_summary", "human_reviewed"}
        for entry in entries
    )
    ids = [entry["semantic_group_id"] for entry in entries]
    assert len(ids) == len(set(ids)), "duplicate semantic scope review group"

    _, _, cases = _load_all()
    normal_group_ids = {
        case["semantic_group_id"]
        for name in ("dev", "holdout")
        for case in cases[name]
    }
    assert set(ids) == normal_group_ids
    assert CORRECTED_SCOPE_GROUP_IDS.isdisjoint(NO_CHANGE_SCOPE_GROUP_IDS)
    assert CORRECTED_SCOPE_GROUP_IDS | NO_CHANGE_SCOPE_GROUP_IDS == normal_group_ids

    disposition_by_id = {
        entry["semantic_group_id"]: entry["disposition"]
        for entry in entries
    }
    assert set(disposition_by_id.values()) <= {"corrected", "no_change"}
    assert {
        group_id
        for group_id, disposition in disposition_by_id.items()
        if disposition == "corrected"
    } == CORRECTED_SCOPE_GROUP_IDS
    assert {
        group_id
        for group_id, disposition in disposition_by_id.items()
        if disposition == "no_change"
    } == NO_CHANGE_SCOPE_GROUP_IDS
    assert all(entry["scope_summary"].strip() for entry in entries)
    assert all(entry["human_reviewed"] is False for entry in entries)


def test_s04_first_ten_groups_stay_dev_forever() -> None:
    """The first ten authored groups are locked to dev and never holdout."""

    _, _, cases = _load_all()
    if not any(cases.values()):
        return  # empty skeleton (pre-S04.6): nothing to leak yet
    for gid in FIRST_TEN_DEV_GROUP_IDS:
        dev_records = [c for c in cases["dev"] if c["semantic_group_id"] == gid]
        assert dev_records, f"{gid}: locked group missing from dev"
        assert all(c["split"] == "dev" for c in dev_records)
        for name in ("holdout", "boundary_dev", "boundary_holdout"):
            assert all(c["semantic_group_id"] != gid for c in cases[name]), (
                f"{gid}: locked group leaked into {name}"
            )


def test_s04_every_span_is_referenced_by_a_case() -> None:
    """No dead spans: each span_id appears in at least one evidence requirement."""

    _, spans, cases = _load_all()
    all_cases = [c for records in cases.values() for c in records]
    used = _span_ids_by_case(all_cases)
    unreferenced = {s["span_id"] for s in spans} - used
    assert not unreferenced, f"spans not referenced by any case: {sorted(unreferenced)}"


# ------------------------------------------------------- final counts (S04.13+)


def test_s04_dataset_manifest_counts_when_present() -> None:
    """Once dataset_manifest.json exists, final counts must match exactly."""

    dataset_manifest = _read_dataset_manifest()
    if dataset_manifest is None:
        return  # S04.13 not reached yet: final counts are not asserted
    _, spans, cases = _load_all()
    normal_dev = [c for c in cases["dev"]]
    normal_holdout = [c for c in cases["holdout"]]
    boundary = [c for c in (*cases["boundary_dev"], *cases["boundary_holdout"])]
    dev_groups = {c["semantic_group_id"] for c in normal_dev}
    holdout_groups = {c["semantic_group_id"] for c in normal_holdout}
    computed = {
        "normal_groups_dev": len(dev_groups),
        "normal_groups_holdout": len(holdout_groups),
        "normal_cases": len(normal_dev) + len(normal_holdout),
        "boundary_groups_dev": len({c["semantic_group_id"] for c in cases["boundary_dev"]}),
        "boundary_groups_holdout": len(
            {c["semantic_group_id"] for c in cases["boundary_holdout"]}
        ),
        "boundary_cases": len(boundary),
        "gold_spans": len(spans),
    }
    counts = dataset_manifest.get("counts")
    assert isinstance(counts, dict), "dataset_manifest.json: counts missing"
    assert counts == computed, f"counts mismatch: manifest={counts} computed={computed}"
    assert computed["normal_groups_dev"] == 30, "dev groups must be 30"
    assert computed["normal_groups_holdout"] == 20, "holdout groups must be 20"
    assert computed["normal_cases"] == 200, "normal cases must be 200"
    assert computed["boundary_cases"] == 40, "boundary cases must be 40"
    review = dataset_manifest.get("review")
    assert isinstance(review, dict), "dataset_manifest.json: review missing"
    assert review.get("holdout_sealed") is False, "holdout may not be sealed pre-review"
    assert review.get("human_reviewed") is False, "human_reviewed must stay false"
    assert "S05 NOT STARTED" in review.get("status", ""), "status must not claim S05"
