"""S05 build_knowledge CLI.

Parses the corpus manifest into the local knowledge SQLite database.
S05 stops at parse / segment / chunk / store: it does NOT call any
embedding, vector store, BM25, hybrid retrieval, query rewrite,
reranker, or LLM answer generation. The build status remains
``BUILDING``; flipping to ``READY`` is S07's job.

Defaults:

- ``--manifest``   ``evaluations/corpus_manifest.json``
- ``--database``   ``data/processed/knowledge.sqlite3``

CLI surface:

- ``--manifest PATH``      override manifest path
- ``--database PATH``      override knowledge database path
- ``--source-id ID``       ingest only this source_id (repeatable)
- ``--validate-only``      verify manifest + hashes + page counts, no writes
- ``--json``               emit machine-readable JSON summary on stdout

The script never auto-deletes or resets the database. Operators must
remove ``data/processed/knowledge.sqlite3`` themselves if a clean
rebuild is desired.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the local package importable when this script is invoked directly
# without installing the project.
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC = _PROJECT_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from local_chip_advisor.knowledge import (  # noqa: E402  (import after sys.path tweak)
    IngestReport,
    load_corpus_manifest,
)
from local_chip_advisor.knowledge.ingest import ingest_corpus  # noqa: E402
from local_chip_advisor.knowledge.repository import (  # noqa: E402
    initialize_knowledge_database,
    open_knowledge_database,
    list_snapshots,
)


DEFAULT_MANIFEST = Path("evaluations/corpus_manifest.json")
DEFAULT_DATABASE = Path("data/processed/knowledge.sqlite3")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_knowledge",
        description=(
            "Parse the S04 corpus manifest into the local knowledge "
            "SQLite database (S05 parse/chunk/store phase only)."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Path to corpus_manifest.json (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"Path to knowledge.sqlite3 (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument(
        "--source-id",
        action="append",
        default=None,
        help="Ingest only this source_id (repeat for multiple).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Verify manifest, hashes, and page counts without writing.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary on stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    manifest = load_corpus_manifest(args.manifest)
    selected = args.source_id or None

    if args.validate_only:
        # No database is opened or created when validating only;
        # build a dry-run ingest report by wrapping the manifest loop
        # in an offline shim.
        report = _validate_only(manifest, selected, quiet_stdout=args.json)
    else:
        args.database.parent.mkdir(parents=True, exist_ok=True)
        connection = initialize_knowledge_database(args.database)
        try:
            report = _run_ingest(
                connection,
                manifest,
                selected,
                validate_only=False,
                quiet_stdout=args.json,
            )
        finally:
            connection.close()

    summary = _summarize(report, args, manifest)

    if args.json:
        json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        _print_human(summary)

    return 0


def _validate_only(
    manifest: object,
    selected: list[str] | None,
    *,
    quiet_stdout: bool,
) -> IngestReport:
    """Run the ingest pipeline with ``validate_only=True`` without a DB."""

    saved_stdout = sys.stdout
    if quiet_stdout:
        sys.stdout = sys.stderr
    try:
        return ingest_corpus(
            None,  # type: ignore[arg-type]
            manifest,
            source_ids=selected,
            validate_only=True,
        )
    finally:
        sys.stdout = saved_stdout


def _run_ingest(
    connection: object,
    manifest: object,
    selected: list[str] | None,
    *,
    validate_only: bool,
    quiet_stdout: bool,
) -> IngestReport:
    """Run the ingest pipeline, optionally silencing non-JSON stdout chatter.

    PyMuDF emits a one-time banner ("Consider using the pymupdf_layout
    package...") to stdout on first use of ``find_tables``. In JSON mode
    we must guarantee that only the JSON document reaches stdout, so we
    swap stdout for stderr for the duration of the ingest call.
    """

    if not quiet_stdout:
        return ingest_corpus(
            connection,
            manifest,
            source_ids=selected,
            validate_only=validate_only,
        )

    saved_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        return ingest_corpus(
            connection,
            manifest,
            source_ids=selected,
            validate_only=validate_only,
        )
    finally:
        sys.stdout = saved_stdout


def _summarize(
    report: IngestReport,
    args: argparse.Namespace,
    manifest: object,
) -> dict[str, object]:
    snapshot = None
    if not args.validate_only:
        connection = open_knowledge_database(args.database)
        try:
            snapshots = list_snapshots(connection)
        finally:
            connection.close()
        if snapshots:
            snap = snapshots[-1]
            snapshot = {
                "snapshot_id": snap.snapshot_id,
                "status": snap.status,
                "document_count": snap.document_count,
                "page_count": snap.page_count,
                "segment_count": snap.segment_count,
                "chunk_count": snap.chunk_count,
                "chunk_link_count": snap.chunk_link_count,
                "needs_ocr_pages": snap.needs_ocr_pages,
                "table_uncertain_pages": snap.table_uncertain_pages,
                "warnings": list(snap.warnings),
            }

    return {
        "build_id": getattr(snapshot or {}, "snapshot_id", None),
        "manifest_path": str(args.manifest),
        "database_path": str(args.database),
        "validate_only": args.validate_only,
        "corpus_id": getattr(manifest, "corpus_id", None),
        "documents_requested": len(getattr(manifest, "documents", ())),
        "documents_processed": report.document_count,
        "pages": report.page_count,
        "segments": report.segment_count,
        "chunks": report.chunk_count,
        "chunk_links": report.chunk_link_total,
        "needs_ocr_pages": report.needs_ocr_pages,
        "table_uncertain_pages": report.table_uncertain_pages,
        "warnings": list(report.warnings),
        "snapshot_status": (snapshot or {}).get("status") if snapshot else None,
        "snapshot": snapshot,
    }


def _print_human(summary: dict[str, object]) -> None:
    print(f"build_id            : {summary.get('build_id')}")
    print(f"corpus_id           : {summary.get('corpus_id')}")
    print(f"documents_requested : {summary.get('documents_requested')}")
    print(f"documents_processed : {summary.get('documents_processed')}")
    print(f"pages               : {summary.get('pages')}")
    print(f"segments            : {summary.get('segments')}")
    print(f"chunks              : {summary.get('chunks')}")
    print(f"chunk_links         : {summary.get('chunk_links')}")
    print(f"needs_ocr_pages     : {summary.get('needs_ocr_pages')}")
    print(f"table_uncertain     : {summary.get('table_uncertain_pages')}")
    print(f"snapshot_status     : {summary.get('snapshot_status')}")
    warnings = summary.get("warnings") or []
    if warnings:
        print("warnings            :")
        for warning in warnings:
            print(f"  - {warning}")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
