"""Contract tests for the build_knowledge CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pymupdf

from local_chip_advisor.knowledge.repository import (
    initialize_knowledge_database,
    list_documents,
    list_snapshots,
    open_knowledge_database,
)


def _write_pdf(path: Path, *, pages: list[str]) -> None:
    document = pymupdf.open()
    for body in pages:
        page = document.new_page()
        page.insert_text((72, 72), body)
    document.save(path)
    document.close()


def _build_manifest(
    path: Path,
    pdf: Path,
    *,
    source_id: str = "synthetic-cli",
    pdf_pages: int = 1,
) -> str:
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest().upper()
    payload = {
        "schema_version": 1,
        "corpus_id": "s05-cli-corpus",
        "documents": [
            {
                "source_id": source_id,
                "manufacturer": "Test Manufacturer",
                "product_ids": ["MP4570"],
                "document_type": "datasheet",
                "document_title": source_id,
                "document_revision": "1.0",
                "document_date": "2026-01-01",
                "language": "en",
                "source_authority": "official_vendor_datasheet",
                "source_url": "https://example/test.pdf",
                "local_file": str(pdf).replace("\\", "/"),
                "sha256": sha,
                "pdf_pages": pdf_pages,
                "source_verified": True,
                "human_reviewed": True,
                "themes_present": [],
                "notes": [],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return sha


def _venv_python() -> str:
    return str(Path(__file__).resolve().parents[1] / ".venv" / "python.exe")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_build_knowledge_help_exits_zero(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            _venv_python(),
            "-B",
            "scripts/build_knowledge.py",
            "--help",
        ],
        cwd=_project_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--manifest" in result.stdout
    assert "--validate-only" in result.stdout
    assert "--json" in result.stdout


def test_build_knowledge_validate_only_does_not_write(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["body text " * 60, "more body text " * 60])
    manifest_path = tmp_path / "corpus_manifest.json"
    _build_manifest(manifest_path, pdf, pdf_pages=2)
    database = tmp_path / "knowledge.sqlite3"

    result = subprocess.run(
        [
            _venv_python(),
            "-B",
            "scripts/build_knowledge.py",
            "--manifest",
            str(manifest_path),
            "--database",
            str(database),
            "--validate-only",
            "--json",
        ],
        cwd=_project_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["validate_only"] is True
    assert payload["documents_processed"] == 1
    # validate-only must not create the database file
    assert not database.exists()


def test_build_knowledge_writes_database(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["body text " * 60, "more body text " * 60])
    manifest_path = tmp_path / "corpus_manifest.json"
    _build_manifest(manifest_path, pdf, pdf_pages=2)
    database = tmp_path / "knowledge.sqlite3"

    result = subprocess.run(
        [
            _venv_python(),
            "-B",
            "scripts/build_knowledge.py",
            "--manifest",
            str(manifest_path),
            "--database",
            str(database),
            "--json",
        ],
        cwd=_project_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["documents_processed"] == 1
    assert payload["pages"] >= 2
    assert payload["chunks"] >= 1
    assert payload["snapshot_status"] == "BUILDING"

    readonly = open_knowledge_database(database)
    try:
        documents = list_documents(readonly)
        snapshots = list_snapshots(readonly)
    finally:
        readonly.close()

    assert len(documents) == 1
    assert len(snapshots) == 1
    assert snapshots[0].status == "BUILDING"


def test_build_knowledge_fails_on_hash_mismatch(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=["body text " * 60])
    manifest_path = tmp_path / "corpus_manifest.json"
    _build_manifest(manifest_path, pdf)
    # Corrupt the recorded SHA after writing the manifest so the file
    # exists but the SHA does not match.
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    database = tmp_path / "knowledge.sqlite3"

    result = subprocess.run(
        [
            _venv_python(),
            "-B",
            "scripts/build_knowledge.py",
            "--manifest",
            str(manifest_path),
            "--database",
            str(database),
        ],
        cwd=_project_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "sha256 mismatch" in result.stderr


def test_build_knowledge_filters_by_source_id(tmp_path: Path) -> None:
    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    _write_pdf(pdf_a, pages=["alpha body text " * 60, "more alpha text " * 60])
    _write_pdf(pdf_b, pages=["beta body text " * 60, "more beta text " * 60])

    sha_a = hashlib.sha256(pdf_a.read_bytes()).hexdigest().upper()
    sha_b = hashlib.sha256(pdf_b.read_bytes()).hexdigest().upper()

    manifest = {
        "schema_version": 1,
        "corpus_id": "s05-cli-corpus",
        "documents": [
            {
                "source_id": "synthetic-a",
                "manufacturer": "Test",
                "product_ids": ["MP4570"],
                "document_type": "datasheet",
                "document_title": "synthetic-a",
                "document_revision": "1.0",
                "document_date": "2026-01-01",
                "language": "en",
                "source_authority": "official_vendor_datasheet",
                "source_url": "https://example/a.pdf",
                "local_file": str(pdf_a).replace("\\", "/"),
                "sha256": sha_a,
                "pdf_pages": 2,
                "source_verified": True,
                "human_reviewed": True,
                "themes_present": [],
                "notes": [],
            },
            {
                "source_id": "synthetic-b",
                "manufacturer": "Test",
                "product_ids": ["MP4570"],
                "document_type": "datasheet",
                "document_title": "synthetic-b",
                "document_revision": "1.0",
                "document_date": "2026-01-01",
                "language": "en",
                "source_authority": "official_vendor_datasheet",
                "source_url": "https://example/b.pdf",
                "local_file": str(pdf_b).replace("\\", "/"),
                "sha256": sha_b,
                "pdf_pages": 2,
                "source_verified": True,
                "human_reviewed": True,
                "themes_present": [],
                "notes": [],
            },
        ],
    }
    manifest_path = tmp_path / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    database = tmp_path / "knowledge.sqlite3"

    result = subprocess.run(
        [
            _venv_python(),
            "-B",
            "scripts/build_knowledge.py",
            "--manifest",
            str(manifest_path),
            "--database",
            str(database),
            "--source-id",
            "synthetic-a",
            "--json",
        ],
        cwd=_project_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["documents_requested"] == 2
    assert payload["documents_processed"] == 1
