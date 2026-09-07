"""S05 gold_chunk_map artifact builder.

For each gold span in ``evaluations/cases/gold_spans.jsonl`` this script
finds the chunks whose ``page_start..page_end`` covers the span's
``pdf_page_start..pdf_page_end`` range and that contain the span's
verbatim text (after whitespace normalization). The result is a
machine-readable map plus a coverage report.

Outputs:

- ``data/processed/gold_chunk_map.json`` — span_id → chunk_id (or null)
  plus per-span diagnostic fields.
- stdout coverage summary (or --json for the full map).

This is a verification-only artifact. It does NOT mutate the knowledge
database and does NOT touch the live catalog. It is read-only against
the SQLite knowledge store and read-only against the gold spans file.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC = _PROJECT_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RUN.sub(" ", text).strip().lower()


def _load_gold_spans(path: Path) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            spans.append(json.loads(stripped))
    return spans


def _source_id_to_doc_id(
    con: sqlite3.Connection, source_id: str
) -> str | None:
    row = con.execute(
        "SELECT doc_id FROM documents WHERE source_id = ?", (source_id,)
    ).fetchone()
    return row[0] if row else None


def _load_chunks_for_doc(
    con: sqlite3.Connection, doc_id: str
) -> list[tuple[str, str, int, int, str]]:
    return list(
        con.execute(
            "SELECT chunk_id, sequence, page_start, page_end, raw_text "
            "FROM chunks WHERE doc_id = ? ORDER BY sequence",
            (doc_id,),
        )
    )


def _candidate_chunks(
    chunks: list[tuple[str, str, int, int, str]],
    page_start: int,
    page_end: int,
) -> list[tuple[str, str, int, int, str]]:
    return [
        c
        for c in chunks
        if c[2] <= page_end and c[3] >= page_start
    ]


def _match_span(
    candidates: list[tuple[str, int, int, str]], verbatim: str
) -> str | None:
    target = _normalize(verbatim)
    if not target:
        return None
    for chunk_id, _ps, _pe, text in candidates:
        if target in _normalize(text):
            return chunk_id
    return None


def _build_map(
    spans: list[dict[str, object]],
    con: sqlite3.Connection,
) -> list[dict[str, object]]:
    """Build a per-span match map.

    For each gold span we record three fields that together characterize
    how cleanly the structural chunker captured it:

    - ``chunk_id``: the single chunk that contains the full verbatim text
      on the recorded page range (the primary contract).
    - ``split_chunk_ids``: chunks whose union holds the verbatim text on
      the recorded page range (heading-crossing case). Empty when the
      verbatim fits in a single chunk.
    - ``nearby_chunk_ids``: chunks on adjacent pages (±1) that contain
      the verbatim text — useful for spans whose recorded page is off by
      one because the chunker merged paragraphs across a page break.
    """

    rows: list[dict[str, object]] = []
    for span in spans:
        source_id = span.get("source_id")
        doc_id = (
            _source_id_to_doc_id(con, str(source_id)) if source_id else None
        )
        chunk_id: str | None = None
        candidate_count = 0
        split_chunk_ids: list[str] = []
        nearby_chunk_ids: list[str] = []
        if doc_id is not None:
            ps = int(span.get("pdf_page_start") or 0)
            pe = int(span.get("pdf_page_end") or ps)
            chunks = _load_chunks_for_doc(con, doc_id)
            candidates = _candidate_chunks(chunks, ps, pe)
            candidate_count = len(candidates)
            verbatim = str(span.get("verbatim_text", ""))
            target = _normalize(verbatim)
            if target:
                # Primary: verbatim contained whole in one chunk.
                for cid, _seq, _cps, _cpe, text in candidates:
                    if target in _normalize(text):
                        chunk_id = cid
                        break
                # Secondary: verbatim covered by union of overlapping chunks
                # on the recorded page range.
                if chunk_id is None:
                    accumulator = ""
                    for cid, _seq, _cps, _cpe, text in candidates:
                        accumulator = (
                            (accumulator + " " + text) if accumulator else text
                        )
                        if target in _normalize(accumulator):
                            split_chunk_ids.append(cid)
                            break
                # Tertiary: verbatim found on adjacent pages (±1).
                if chunk_id is None and not split_chunk_ids:
                    for cid, _seq, cps, cpe, text in _candidate_chunks(
                        chunks, max(1, ps - 1), pe + 1
                    ):
                        if target in _normalize(text):
                            nearby_chunk_ids.append(cid)
        rows.append(
            {
                "span_id": span.get("span_id"),
                "source_id": source_id,
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "split_chunk_ids": split_chunk_ids,
                "nearby_chunk_ids": nearby_chunk_ids,
                "pdf_page_start": span.get("pdf_page_start"),
                "pdf_page_end": span.get("pdf_page_end"),
                "candidate_count": candidate_count,
                "section": span.get("section"),
            }
        )
    return rows


def _coverage_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    total = len(rows)
    matched = sum(1 for r in rows if r["chunk_id"] is not None)
    per_source: dict[str, dict[str, int]] = {}
    for r in rows:
        src = str(r.get("source_id") or "<unknown>")
        bucket = per_source.setdefault(
            src, {"total": 0, "matched": 0, "missing": 0}
        )
        bucket["total"] += 1
        if r["chunk_id"] is None:
            bucket["missing"] += 1
        else:
            bucket["matched"] += 1
    unmatched = [r["span_id"] for r in rows if r["chunk_id"] is None]
    return {
        "total_spans": total,
        "matched": matched,
        "missing": total - matched,
        "match_rate": (matched / total) if total else 0.0,
        "by_source": per_source,
        "unmatched_span_ids": unmatched,
    }


def _write_artifact(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build_gold_chunk_map",
        description=(
            "Verify that every gold span in evaluations/cases/gold_spans.jsonl "
            "is contained in at least one chunk on the right page range, "
            "and write the resulting chunk-id map to data/processed/."
        ),
    )
    parser.add_argument(
        "--spans",
        type=Path,
        default=Path("evaluations/cases/gold_spans.jsonl"),
        help="Path to gold_spans.jsonl",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/processed/knowledge.sqlite3"),
        help="Path to knowledge.sqlite3",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/gold_chunk_map.json"),
        help="Output artifact path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full map as JSON on stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    spans = _load_gold_spans(args.spans)
    if not args.database.exists():
        print(f"ERROR: database not found: {args.database}", file=sys.stderr)
        return 2
    con = sqlite3.connect(str(args.database))
    try:
        rows = _build_map(spans, con)
    finally:
        con.close()
    summary = _coverage_summary(rows)
    payload = {
        "schema_version": 1,
        "spans_total": len(spans),
        "summary": summary,
        "matches": rows,
    }
    _write_artifact(args.out, payload)
    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    print(f"spans_total : {summary['total_spans']}")
    print(f"matched     : {summary['matched']}")
    print(f"missing     : {summary['missing']}")
    print(f"match_rate  : {summary['match_rate']:.2%}")
    print("by_source:")
    for src, bucket in sorted(summary["by_source"].items()):
        rate = bucket["matched"] / bucket["total"] if bucket["total"] else 0.0
        print(
            f"  - {src}: matched={bucket['matched']}/{bucket['total']} "
            f"({rate:.0%}) missing={bucket['missing']}"
        )
    if summary["unmatched_span_ids"]:
        print("unmatched_span_ids:")
        for sid in summary["unmatched_span_ids"]:
            print(f"  - {sid}")
    print(f"artifact    : {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
