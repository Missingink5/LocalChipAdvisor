"""Deterministic selection and small-scale hybrid retrieval."""
from __future__ import annotations

import numpy as np

from .llm import OllamaEmbeddingClient
from .models import CandidateResult, ParsedQuery, SearchHit
from .store import ChipStore


def deterministic_select(store: ChipStore, parsed: ParsedQuery) -> list[CandidateResult]:
    return store.filter_products(parsed)


def rrf_fusion(bm25_ids: list[str], vector_ids: list[str], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in (bm25_ids, vector_ids):
        for rank, evidence_id in enumerate(ranking, 1):
            scores[evidence_id] = scores.get(evidence_id, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_search(
    store: ChipStore, parsed: ParsedQuery, embedder: OllamaEmbeddingClient | None,
    *, limit: int = 6,
) -> list[SearchHit]:
    product_ids: list[str] = []
    for part in parsed.part_numbers:
        product = store.get_product_by_part_number(part)
        if product:
            product_ids.append(product.product_id)
    if parsed.part_numbers and not product_ids:
        return []

    query = parsed.semantic_query or parsed.raw_query
    for part in parsed.part_numbers:
        query = query.replace(part, "")
    query = _expand_query(query)
    fts = store.search_fts(query, product_ids=product_ids or None, limit=20)
    use_vector = _semantic_question(query) or len(fts) < 5
    vector_ranked = []
    if use_vector and embedder and product_ids:
        stored = store.get_embeddings_for_filtered_chunks(product_ids, embedder.model)
        if stored:
            query_vector = store.load_cached_query_embedding(query, embedder.model)
            if query_vector is None:
                query_vector = np.asarray(embedder.embed_texts([query])[0], dtype=np.float32)
                store.cache_query_embedding(query, embedder.model, query_vector.tolist())
            scored = [(evidence, _cosine(query_vector, vector)) for evidence, vector in stored]
            vector_ranked = [item[0] for item in sorted(scored, key=lambda x: x[1], reverse=True)[:20]]

    bm25_ids = [item.evidence_id for item in fts]
    vector_ids = [item.evidence_id for item in vector_ranked]
    scores = rrf_fusion(bm25_ids, vector_ids)
    by_id = {item.evidence_id: item for item in [*fts, *vector_ranked]}
    bm25_rank = {item: i for i, item in enumerate(bm25_ids, 1)}
    vector_rank = {item: i for i, item in enumerate(vector_ids, 1)}
    ordered = sorted(scores, key=scores.get, reverse=True)
    topic_fields = _topic_fields(query)
    if topic_fields:
        matching = [item for item in ordered if by_id[item].field_name in topic_fields]
        if matching:
            ordered = matching
    ordered = ordered[:limit]
    return [SearchHit(evidence=by_id[item], bm25_rank=bm25_rank.get(item),
                      vector_rank=vector_rank.get(item), rrf_score=scores[item])
            for item in ordered]


def _semantic_question(query: str) -> bool:
    lowered = query.casefold()
    return any(term in lowered for term in (
        "为什么", "怎么", "如何", "以后", "原理", "机制", "行为", "how", "why", "mechanism"
    ))


def _expand_query(query: str) -> str:
    lowered = query.casefold()
    additions = []
    glossary = {
        "短路": "short circuit hiccup protection",
        "恢复": "recovery retry restart",
        "过温": "thermal shutdown over temperature",
        "轻载": "light load pulse skipping",
        "浪涌": "surge transient",
    }
    for source, target in glossary.items():
        if source in lowered:
            additions.append(target)
    return " ".join([query, *additions]).strip()


def _topic_fields(query: str) -> set[str]:
    lowered = query.casefold()
    topics: set[str] = set()
    if "短路" in lowered or "short circuit" in lowered or "hiccup" in lowered:
        topics.add("short_circuit_protection")
    if "过温" in lowered or "thermal" in lowered or "over temperature" in lowered:
        topics.add("otp")
    return topics


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    if left.size != right.size:
        return -1.0
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else -1.0
