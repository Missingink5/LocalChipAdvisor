"""Dev-only retrieval evaluation; annotations never enter retrieval or generation."""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00ad", "")).strip().lower()


def span_covered(span: dict, evidence: list[dict]) -> bool:
    """Require full text, hash and physical-page coverage within one document."""
    groups: dict[str, list[dict]] = {}
    first, last = span["pdf_page_start"], span["pdf_page_end"]
    for record in evidence:
        if (record["document_sha256"].upper() == span["source_sha256"].upper()
                and record["page_start"] <= last and record["page_end"] >= first):
            groups.setdefault(record["doc_id"], []).append(record)
    target = normalize(span["verbatim_text"])
    for records in groups.values():
        pages = {p for record in records
                 for p in range(record["page_start"], record["page_end"] + 1)}
        if not set(range(first, last + 1)) <= pages:
            continue
        ordered = sorted(records, key=lambda r: (r["page_start"], r.get("sequence", 0)))
        text = ""
        for record in ordered:
            part = normalize(record.get("raw_text", record["text"]))
            if part in text:
                continue
            # Remove exact suffix/prefix overlap without dropping other content.
            overlap = 0
            for length in range(min(len(text), len(part)), 0, -1):
                if text[-length:] == part[:length]:
                    overlap = length
                    break
            text += part[overlap:] if overlap else " " + part
        if target and target in text:
            return True
    return False


def coverage(case: dict, spans: dict, evidence: list[dict]) -> dict:
    requirements = case["gold_evidence_requirements"]
    matched = [r["requirement_id"] for r in requirements
               if any(span_covered(spans[s], evidence) for s in r["alternative_span_ids"])]
    return {"required_count": len(requirements), "matched_requirements": matched,
            "full_evidence": len(matched) == len(requirements) if requirements else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--answers", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    from local_chip_advisor.mvp.index import Index
    from local_chip_advisor.mvp.service import AdvisorService
    from local_chip_advisor.mvp.understanding import understand

    cases = []
    for name in ("dev.jsonl", "boundary_dev.jsonl"):
        cases.extend(json.loads(line) for line in
                     (ROOT / "evaluations/cases" / name).read_text("utf-8").splitlines() if line.strip())
    if any(c["split"] != "dev" for c in cases):
        raise ValueError("Only dev cases are permitted")
    # Filter shared span file immediately to IDs referenced by dev cases.
    needed = {s for c in cases for r in c["gold_evidence_requirements"]
              for s in r["alternative_span_ids"]}
    spans = {}
    for line in (ROOT / "evaluations/cases/gold_spans.jsonl").read_text("utf-8").splitlines():
        span = json.loads(line)
        if span["span_id"] in needed:
            spans[span["span_id"]] = span
    if args.limit:
        cases = cases[:args.limit]
    service = AdvisorService(args.manifest) if args.answers else None
    index = service.index if service else Index(args.manifest)
    report = {"split": "dev", "manifest": str(args.manifest.resolve()),
              "metric": "All AND requirements, at least one complete OR span each; hash and page bound",
              "answer_caveat": "Status agreement is not a semantic factuality audit.",
              "counts": {"cases": len(cases)}, "by_language": {}, "per_case": []}
    for case in cases:
        row = {"case_id": case["case_id"], "language": case["language_group"],
               "expected_status": case["expected_status"], "retrieval": {}}
        for mode in ("dense", "hybrid"):
            start = time.perf_counter()
            try:
                evidence = index.search(case["query"], understand(case["query"])["products"], mode=mode)
                row["retrieval"][mode] = {**coverage(case, spans, evidence),
                                           "ids": [r["chunk_id"] for r in evidence]}
            except Exception as exc:  # noqa: BLE001 - record failures rather than inflate recall by omitting cases.
                row["retrieval"][mode] = {"full_evidence": False if case["gold_evidence_requirements"] else None,
                                           "error": f"{type(exc).__name__}: {exc}"}
            row["retrieval"][mode]["seconds"] = round(time.perf_counter() - start, 3)
        if service:
            answer = service.ask(case["query"])
            selected_ids = {q["chunk_id"] for q in answer["quotes"]}
            selected = [r for r in answer["evidence"] if r["chunk_id"] in selected_ids]
            row["answer"] = {"status": answer["status"], "timings": answer["timings"],
                             "status_matches": answer["status"] == case["expected_status"],
                             "selected_coverage": coverage(case, spans, selected)}
        report["per_case"].append(row)
        print(f"Evaluated {len(report['per_case'])}/{len(cases)} {case['case_id']}", flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    for language in sorted({c["language_group"] for c in cases}):
        rows = [r for r in report["per_case"] if r["language"] == language]
        summary = {"cases": len(rows)}
        for mode in ("dense", "hybrid"):
            eligible = [r["retrieval"][mode] for r in rows
                        if r["retrieval"][mode]["full_evidence"] is not None]
            hits = sum(r["full_evidence"] for r in eligible)
            summary[mode] = {"eligible": len(eligible), "full_evidence_hits": hits,
                             "full_evidence_recall": hits / len(eligible) if eligible else None,
                             "errors": sum("error" in r["retrieval"][mode] for r in rows)}
        report["by_language"][language] = summary
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
