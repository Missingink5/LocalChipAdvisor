"""Build the SQLite database from the reviewed product/document manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from local_chip_advisor.llm import OllamaEmbeddingClient
from local_chip_advisor.models import Evidence, Product
from local_chip_advisor.store import ChipStore


def _section(text: str) -> str | None:
    for line in text.splitlines():
        candidate = " ".join(line.split()).strip()
        if 3 <= len(candidate) <= 80 and candidate.upper() == candidate and re.search(r"[A-Z]", candidate):
            return candidate
    return None


def _field_name(text: str) -> str | None:
    lowered = text.casefold()
    for field, terms in (
        ("short_circuit_protection", ("short circuit", "output short")),
        ("otp", ("thermal shutdown", "over-temperature protection")),
        ("ovp", ("over voltage protection", "over-voltage protection")),
        ("uvlo", ("under voltage lockout", "under-voltage lockout", "uvlo")),
    ):
        if any(term in lowered for term in terms):
            return field
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "data" / "chip_advisor.db"))
    parser.add_argument("--products", default=str(ROOT / "data" / "products.json"))
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.reset:
        for path in (db_path, Path(str(db_path) + "-shm"), Path(str(db_path) + "-wal")):
            path.unlink(missing_ok=True)
    payload = json.loads(Path(args.products).read_text(encoding="utf-8"))
    store = ChipStore(db_path)
    store.init_db()
    for raw in payload["products"]:
        store.upsert_product(Product.model_validate(raw))

    chunk_count = 0
    for document in payload["documents"]:
        pdf_path = ROOT / document["path"]
        actual_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        if actual_hash != document["sha256"]:
            raise RuntimeError(f"SHA-256 mismatch: {pdf_path}")
        product = next(item for item in payload["products"]
                       if item["product_id"] == document["product_id"])
        with pymupdf.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf, 1):
                page_text = page.get_text()
                normalized = " ".join(page_text.split())
                if not normalized:
                    continue
                section = _section(page_text)
                for chunk_index, start in enumerate(range(0, len(normalized), 1200)):
                    text = normalized[start:start + 1500]
                    identity = f"{document['document_id']}:{actual_hash}:{page_number}:{chunk_index}:{text}"
                    evidence_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
                    store.insert_evidence(Evidence(
                        evidence_id=evidence_id,
                        product_id=document["product_id"],
                        document_id=document["document_id"],
                        page=page_number,
                        section=section,
                        field_name=_field_name(text),
                        text=text,
                        reviewed=bool(document["reviewed"] and product["reviewed"]),
                    ))
                    chunk_count += 1

    embedded = 0
    if args.embed:
        embedder = OllamaEmbeddingClient()
        rows = store.conn.execute(
            """SELECT c.evidence_id,c.text FROM evidence_chunks c
            LEFT JOIN chunk_embeddings e ON e.evidence_id=c.evidence_id AND e.embedding_model=?
            WHERE e.evidence_id IS NULL ORDER BY c.evidence_id""", (embedder.model,)
        ).fetchall()
        for offset in range(0, len(rows), 16):
            batch = rows[offset:offset + 16]
            vectors = embedder.embed_texts([row["text"] for row in batch])
            for row, vector in zip(batch, vectors, strict=True):
                store.save_chunk_embedding(row["evidence_id"], embedder.model, vector)
                embedded += 1
        embedder.close()
    print(f"数据库：{db_path}")
    print(f"产品：{len(payload['products'])}；文档：{len(payload['documents'])}；证据块：{chunk_count}；新增向量：{embedded}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
