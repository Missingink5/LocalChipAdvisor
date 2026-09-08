"""Small immutable local vector/BM25 index. Never consumes evaluation annotations."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path

import chromadb
import httpx
from chromadb.config import Settings
from rank_bm25 import BM25Okapi

MODEL = "qwen3-embedding:0.6b"
QUERY_PREFIX = "Instruct: Retrieve relevant semiconductor datasheet passages for the query.\nQuery: "
BM25_CONFIG = {"k1": 1.5, "b": 0.75, "epsilon": 0.25,
               "tokenizer": "ascii-alnum-cjk-unigram-v1",
               "query_expansion": "bilingual-power-terms-v1"}

# Auditable terminology normalization for the lexical channel.  The original
# question is always retained for dense retrieval; no numbers, products or
# negations are rewritten.
QUERY_TERMS = (
    (r"上电|爬升|软启动|启动", "soft start startup ramp pre-biased output tracking"),
    (r"空载|自己耗|静态电流", "quiescent current no load supply current"),
    (r"输入.*输出.*接近|输出.*输入.*接近|占空比高", "dropout high duty cycle bootstrap refresh"),
    (r"改输出电压|设置输出|输出电压.*调", "output voltage feedback resistor divider VFB"),
    (r"迟滞电流|内部上拉|不接\s*EN", "enable EN hysteresis current internal pull-up"),
    (r"欠压|UVP", "output undervoltage protection UVP hiccup restart"),
    (r"太热|过温|热关断|TSD", "thermal shutdown temperature recovery hysteresis"),
    (r"频率|最低能到", "switching frequency minimum frequency foldback"),
    (r"低侧管压降|谷值限流|逐周期", "low-side MOSFET voltage valley current limit cycle-by-cycle"),
    (r"短路", "short circuit soft-start discharge current limit recovery"),
    (r"过压|OVP", "output overvoltage protection OVP threshold behavior"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())


def expand_query(query: str) -> str:
    terms = [english for pattern, english in QUERY_TERMS
             if re.search(pattern, query, re.IGNORECASE)]
    return query if not terms else query + " " + " ".join(terms)


def validate_vectors(vectors: list[list[float]]) -> None:
    if not vectors or not vectors[0]:
        raise RuntimeError("Empty embedding vectors")
    dimension = len(vectors[0])
    if any(len(vector) != dimension or not all(math.isfinite(x) for x in vector)
           or not any(x != 0 for x in vector) for vector in vectors):
        raise RuntimeError("Invalid embedding dimension, nonfinite or zero vector")


def model_digest(client: httpx.Client, model: str) -> str:
    response = client.get("/api/tags")
    response.raise_for_status()
    for item in response.json()["models"]:
        if item["name"] == model or item.get("model") == model:
            return item["digest"]
    raise RuntimeError(f"Ollama embedding model unavailable: {model}")


def is_model_loaded(client: httpx.Client, model: str) -> bool:
    """True when Ollama currently has `model` in VRAM (size_vram > 0)."""
    response = client.get("/api/ps")
    response.raise_for_status()
    for item in response.json().get("models", []):
        if item.get("name") == model and (item.get("size_vram") or 0) > 0:
            return True
    return False


def embed(client: httpx.Client, texts: list[str], model: str) -> list[list[float]]:
    response = client.post("/api/embed", json={"model": model, "input": texts,
                                               "truncate": False, "keep_alive": "30m"})
    response.raise_for_status()
    vectors = response.json()["embeddings"]
    if len(vectors) != len(texts) or not vectors or not vectors[0]:
        raise RuntimeError("Invalid embedding response")
    validate_vectors(vectors)
    return vectors


def build(database: Path, output: Path, base_url: str = "http://127.0.0.1:11434",
          model: str = MODEL) -> Path:
    database = database.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    with httpx.Client(base_url=base_url, timeout=180, trust_env=False) as client:
        fingerprint = model_digest(client, model)
        identity = {"database_sha256": digest(database), "model": model,
                    "model_digest": fingerprint, "query_prefix": QUERY_PREFIX,
                    "bm25": BM25_CONFIG, "schema_version": 1}
        identity_path = output / "build_identity.json"
        if identity_path.exists():
            if json.loads(identity_path.read_text("utf-8")) != identity:
                raise RuntimeError("Different build exists; choose a new output directory")
        elif any(output.iterdir()):
            raise RuntimeError("Nonempty output lacks build identity; choose a new directory")
        else:
            identity_path.write_text(json.dumps(identity, indent=2), encoding="utf-8")
        build_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        if manifest_path.exists() and "build_id" in json.loads(manifest_path.read_text("utf-8")):
            Index(manifest_path)
            return manifest_path
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT c.*, d.source_url, d.document_revision, d.local_file, d.sha256 "
                "FROM chunks c JOIN documents d USING(doc_id) "
                "WHERE c.quality_status='OK' AND d.document_reviewed=1 "
                "ORDER BY c.doc_id,c.sequence").fetchall()
            products = {}
            for row in connection.execute("SELECT doc_id,product_id FROM document_products"):
                products.setdefault(row[0], []).append(row[1])
        records = [{"chunk_id": r["chunk_id"], "doc_id": r["doc_id"],
                    "text": r["raw_text"], "raw_text": r["raw_text"],
                    "retrieval_text": r["retrieval_text"], "page_start": r["page_start"],
                    "page_end": r["page_end"], "sequence": r["sequence"],
                    "source_url": r["source_url"], "revision": r["document_revision"],
                    "source_file": r["local_file"], "document_sha256": r["sha256"],
                    "products": products.get(r["doc_id"], [])} for r in rows]
        if not records:
            raise RuntimeError("No valid chunks")
        sources = {}
        for record in records:
            sources[record["source_file"]] = record["document_sha256"]
        source_files = []
        for relative, expected in sources.items():
            path = (database.parents[2] / relative).resolve()
            if not path.is_file() or digest(path) != expected.lower():
                raise RuntimeError(f"Source PDF missing or hash mismatch: {path}")
            source_files.append({"path": str(path), "sha256": expected.lower()})
        (output / "records.json").write_text(json.dumps(records, ensure_ascii=False), "utf-8")
        vectors = []
        cache = output / "embedding_batches"
        cache.mkdir(exist_ok=True)
        for start in range(0, len(records), 16):
            path = cache / f"{start:06d}.json"
            if path.exists():
                batch = json.loads(path.read_text("utf-8"))
            else:
                batch = embed(client, [r["retrieval_text"] for r in records[start:start+16]], model)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(batch), "utf-8")
                temporary.replace(path)
            if len(batch) != len(records[start:start+16]):
                raise RuntimeError("Embedding cache count mismatch")
            vectors.extend(batch)
            print(f"Embedded {len(vectors)}/{len(records)}", flush=True)
        dimension = len(vectors[0])
        validate_vectors(vectors)
        if model_digest(client, model) != fingerprint:
            raise RuntimeError("Model changed while building")
        chroma = chromadb.PersistentClient(path=str(output / "chroma"),
                                          settings=Settings(anonymized_telemetry=False))
        collection = chroma.get_or_create_collection("datasheets", metadata={"hnsw:space": "cosine"})
        for start in range(0, len(records), 256):
            batch_records = records[start:start+256]
            collection.upsert(ids=[r["chunk_id"] for r in batch_records],
                              embeddings=vectors[start:start+256],
                              metadatas=[{"doc_id": r["doc_id"]} for r in batch_records])
        if collection.count() != len(records):
            raise RuntimeError("Chroma count mismatch")
        records_hash = digest(output / "records.json")
        collection.modify(metadata={"build_id": build_id,
                                    "records_sha256": records_hash,
                                    "model_digest": fingerprint, "dimension": dimension})
        manifest = {**identity, "status": "READY", "dimension": dimension,
                    "chunk_count": len(records), "base_url": base_url,
                    "build_id": build_id, "records_sha256": records_hash,
                    "source_files": source_files, "bm25": BM25_CONFIG,
                    "chunker_versions": sorted({r["chunker_version"] for r in rows}),
                    "parser": "existing-reviewed-S05-knowledge-sqlite",
                    "fusion": {"method": "RRF", "k": 60, "per_retriever": 40}}
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2), "utf-8")
        temporary.replace(manifest_path)
    return manifest_path


class Index:
    def __init__(self, manifest: Path):
        self.path = Path(manifest).resolve()
        self.manifest = json.loads(self.path.read_text("utf-8"))
        if self.manifest["status"] != "READY":
            raise RuntimeError("Index not READY")
        records_path = self.path.parent / "records.json"
        if digest(records_path) != self.manifest["records_sha256"]:
            raise RuntimeError("Index records hash mismatch")
        self.records = json.loads(records_path.read_text("utf-8"))
        self.by_id = {r["chunk_id"]: r for r in self.records}
        signatures = Counter((r["doc_id"], re.sub(r"\s+", " ", r["text"]).strip())
                             for r in self.records)
        self.noisy_ids = {r["chunk_id"] for r in self.records
                          if len(r["text"]) < 200 and
                          signatures[(r["doc_id"], re.sub(r"\s+", " ", r["text"]).strip())] > 3}
        if len(self.by_id) != self.manifest["chunk_count"]:
            raise RuntimeError("Duplicate chunks or manifest count mismatch")
        for source in self.manifest["source_files"]:
            path = Path(source["path"])
            if not path.is_file() or digest(path) != source["sha256"]:
                raise RuntimeError(f"Source PDF missing or hash mismatch: {path}")
        self.client = httpx.Client(base_url=self.manifest["base_url"], timeout=180, trust_env=False)
        self.chroma = chromadb.PersistentClient(path=str(self.path.parent / "chroma"),
                                               settings=Settings(anonymized_telemetry=False))
        self.collection = self.chroma.get_collection("datasheets")
        if self.collection.count() != len(self.records):
            raise RuntimeError("Chroma count mismatch")
        metadata = self.collection.metadata or {}
        for key in ("build_id", "records_sha256", "model_digest", "dimension"):
            if metadata.get(key) != self.manifest.get(key) or key not in self.manifest:
                raise RuntimeError(f"Chroma fingerprint mismatch: {key}")
        if set(self.collection.get(include=[])["ids"]) != set(self.by_id):
            raise RuntimeError("Chroma chunk IDs mismatch")

    def search(self, query: str, products: list[str], mode: str = "hybrid",
               top_k: int = 12, chat_model: str | None = None) -> list[dict]:
        """mode "auto": bm25 when chat_model is already loaded, else hybrid.

        Embedding the query loads qwen3-embedding:0.6b into VRAM. On the
        8 GiB RTX 4060 Laptop WDDM that evicts the resident chat model
        and forces a ~6.5s reload on the next chat call. When the chat
        model is already loaded and the question is in scope, bm25-only
        avoids the swap entirely.
        """
        if mode not in {"hybrid", "dense", "bm25", "auto"}:
            raise ValueError("mode must be hybrid, dense, bm25 or auto")
        if mode == "auto":
            if chat_model and is_model_loaded(self.client, chat_model):
                mode = "bm25"
            else:
                mode = "hybrid"
        allowed = {p.upper() for p in products}
        records = [r for r in self.records if r["chunk_id"] not in self.noisy_ids and
                   (not allowed or allowed.intersection(p.upper() for p in r["products"]))]
        if not records:
            return []
        ranks = []
        if mode in {"hybrid", "dense"}:
            if model_digest(self.client, self.manifest["model"]) != self.manifest["model_digest"]:
                raise RuntimeError("Embedding model fingerprint changed; rebuild index")
            vector = embed(self.client, [QUERY_PREFIX + query], self.manifest["model"])[0]
            if len(vector) != self.manifest["dimension"]:
                raise RuntimeError("Query embedding dimension mismatch")
            docs = sorted({r["doc_id"] for r in records})
            result = self.collection.query(query_embeddings=[vector],
                                           where={"doc_id": {"$in": docs}},
                                           n_results=min(120, len(records)))
            ranks.append([chunk_id for chunk_id in result["ids"][0]
                          if chunk_id not in self.noisy_ids][:40])
        if mode in {"hybrid", "bm25"}:
            bm25 = BM25Okapi([tokens(r["retrieval_text"]) or ["_"] for r in records],
                            k1=1.5, b=0.75, epsilon=0.25)
            product_tokens = {token for product in allowed for token in tokens(product)}
            scores = bm25.get_scores([token for token in tokens(expand_query(query))
                                      if token not in product_tokens])
            ranks.append([records[i]["chunk_id"] for i in
                          sorted(range(len(records)), key=lambda i: scores[i], reverse=True)[:40]
                          if scores[i] > 0])
        fused = {}
        for rank in ranks:
            for position, chunk_id in enumerate(rank, 1):
                fused[chunk_id] = fused.get(chunk_id, 0) + 1 / (60 + position)
        selected = []
        seen_text = set()
        budget = 11000
        for chunk_id in sorted(fused, key=fused.get, reverse=True):
            record = self.by_id[chunk_id]
            signature = (record["doc_id"], re.sub(r"\s+", " ", record["text"]).strip())
            if signature in seen_text:
                continue
            if len(record["text"]) > budget:
                continue
            selected.append({**record, "score": fused[chunk_id]})
            seen_text.add(signature)
            budget -= len(record["text"])
            if len(selected) >= top_k:
                break
        return selected
