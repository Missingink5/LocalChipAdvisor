import hashlib
import json
from pathlib import Path

import pymupdf

from local_chip_advisor.models import Product

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "products.json"


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_real_manifest_has_three_chips_and_four_documents():
    payload = _manifest()
    products = [Product.model_validate(item) for item in payload["products"]]
    assert {item.part_number for item in products} == {"MP4570", "MPQ4570", "MP023"}
    assert len(payload["documents"]) == 4
    assert sum(item["kind"] == "evaluation_board" for item in payload["documents"]) == 1


def test_document_hashes_and_field_evidence_anchors_match_declared_pages():
    payload = _manifest()
    documents = {item["document_id"]: item for item in payload["documents"]}
    for document in documents.values():
        path = ROOT / document["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == document["sha256"]
    for evidence in payload["evidence"]:
        document = documents[evidence["document_id"]]
        with pymupdf.open(ROOT / document["path"]) as pdf:
            page_text = " ".join(pdf[evidence["page"] - 1].get_text().split())
        assert evidence["match"].casefold() in page_text.casefold(), evidence["evidence_id"]
