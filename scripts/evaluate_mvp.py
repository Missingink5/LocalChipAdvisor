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
    parser.add_argument("--mode", choices=["retrieval", "answers", "both"],
                        default="retrieval",
                        help="retrieval: dense+hybrid benchmark only (no chat model); "
                             "answers: answer pipeline only (no extra retrieval benchmark); "
                             "both: full report (retrieval benchmark + answers)")
    parser.add_argument("--answers", action="store_true",
                        help="deprecated alias for --mode both")
    parser.add_argument("--profile", choices=["fast", "audit", "strict"],
                        default=None,
                        help="answer pipeline profile (default: module default)")
    parser.add_argument("--ids", type=str, default=None,
                        help="comma-separated case_id filter (subset of dev + "
                             "boundary_dev); applied before --limit")
    parser.add_argument("--num-ctx", type=int, default=None,
                        help="override ChatClient num_ctx (default: AdvisorService default 8192)")
    parser.add_argument("--audit-num-predict", type=int, default=800,
                        help="num_predict for the audit stage (default 800)")
    parser.add_argument("--retrieval-mode", type=str, default="hybrid",
                        help="Index.search mode (hybrid, bm25, dense, auto); default hybrid")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.limit is not None and args.ids is not None:
        parser.error("--limit and --ids are mutually exclusive")
    if args.answers:
        args.mode = "both"
    do_retrieval = args.mode in {"retrieval", "both"}
    do_answers = args.mode in {"answers", "both"}
    from local_chip_advisor.mvp.index import Index
    from local_chip_advisor.mvp.service import AdvisorService
    from local_chip_advisor.mvp.understanding import understand

    cases = []
    for name in ("dev.jsonl", "boundary_dev.jsonl"):
        cases.extend(json.loads(line) for line in
                     (ROOT / "evaluations/cases" / name).read_text("utf-8").splitlines() if line.strip())
    if any(c["split"] != "dev" for c in cases):
        raise ValueError("Only dev cases are permitted")
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        cases = [c for c in cases if c["case_id"] in wanted]
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
    service = AdvisorService(args.manifest, pipeline_profile=args.profile,
                             num_ctx=args.num_ctx) if do_answers else None
    if service is not None:
        service.retrieval_mode = args.retrieval_mode
    index = service.index if service else Index(args.manifest)
    report = {"split": "dev", "manifest": str(args.manifest.resolve()),
              "metric": "All AND requirements, at least one complete OR span each; hash and page bound",
              "answer_caveat": "Status agreement is not a semantic factuality audit.",
              "mode": args.mode,
              "counts": {"cases": len(cases)}, "by_language": {}, "per_case": []}
    answer_summary: dict = {"status_counts": {}, "model_error": 0,
                            "insufficient_evidence": 0, "citation_violations": 0,
                            "seconds": []}
    for case in cases:
        row = {"case_id": case["case_id"], "language": case["language_group"],
               "expected_status": case["expected_status"]}
        if do_retrieval:
            row["retrieval"] = {}
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
        if do_answers:
            answer = service.ask(case["query"])
            selected_ids = {q["chunk_id"] for q in answer["quotes"]}
            selected = [r for r in answer["evidence"] if r["chunk_id"] in selected_ids]
            violations = [q["chunk_id"] for q in answer["quotes"]
                          if q["chunk_id"] not in service.index.by_id]
            row["answer"] = {"status": answer["status"], "timings": answer["timings"],
                             "status_matches": answer["status"] == case["expected_status"],
                             "selected_coverage": coverage(case, spans, selected),
                             "citation_violations": violations,
                             "answer_text": (answer.get("answer_text") or "")[:200],
                             "message": answer.get("message", ""),
                             "diagnostics": answer.get("diagnostics", {})}
            answer_summary["status_counts"][answer["status"]] = \
                answer_summary["status_counts"].get(answer["status"], 0) + 1
            if answer["status"] == "MODEL_ERROR":
                answer_summary["model_error"] += 1
            if answer["status"] == "INSUFFICIENT_EVIDENCE":
                answer_summary["insufficient_evidence"] += 1
            answer_summary["citation_violations"] += len(violations)
            if answer["timings"].get("total_seconds"):
                answer_summary["seconds"].append(answer["timings"]["total_seconds"])
        report["per_case"].append(row)
        print(f"Evaluated {len(report['per_case'])}/{len(cases)} {case['case_id']}", flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    if do_retrieval:
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
    if do_answers:
        seconds = sorted(answer_summary["seconds"])
        answer_summary["seconds"] = {
            "count": len(seconds), "total": round(sum(seconds), 1),
            "mean": round(sum(seconds) / len(seconds), 1) if seconds else None,
            "median": round(seconds[len(seconds) // 2], 1) if seconds else None,
        }
        report["answer_summary"] = answer_summary
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
