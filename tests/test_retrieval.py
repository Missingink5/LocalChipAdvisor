
from local_chip_advisor.models import Evidence, Intent, ParsedQuery, Product
from local_chip_advisor.retrieval import hybrid_search, rrf_fusion
from local_chip_advisor.store import ChipStore


class FakeEmbedder:
    model = "fake"
    calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        return [[1.0, 0.0] for _ in texts]


def test_metadata_filter_fts_and_vector_cache(tmp_path):
    store = ChipStore(tmp_path / "test.db")
    store.init_db()
    for pid, part in (("a", "DEMO-A-001"), ("b", "DEMO-B-001")):
        store.upsert_product(Product(product_id=pid, part_number=part, category="DC-DC",
                                     topology="Buck", reviewed=True))
        ev = Evidence(evidence_id=f"e-{pid}", product_id=pid, document_id=f"d-{pid}",
                      page=1, section="OCP", text="short circuit hiccup protection", reviewed=True)
        store.insert_evidence(ev)
        store.save_chunk_embedding(ev.evidence_id, "fake", [1, 0] if pid == "a" else [0, 1])
    parsed = ParsedQuery(raw_query="DEMO-A-001 short circuit how", intent=Intent.PART_QA,
                         part_numbers=["DEMO-A-001"], semantic_query="short circuit how")
    embedder = FakeEmbedder()
    hits = hybrid_search(store, parsed, embedder)
    assert hits and {hit.evidence.product_id for hit in hits} == {"a"}
    assert embedder.calls == 1
    hybrid_search(store, parsed, embedder)
    assert embedder.calls == 1
    store.close()


def test_topic_gate_keeps_thermal_evidence_out_of_short_circuit_answer(tmp_path):
    store = ChipStore(tmp_path / "topics.db")
    store.init_db()
    store.upsert_product(Product(product_id="a", part_number="DEMO-A-001", category="DC-DC",
                                 topology="Buck", reviewed=True))
    short = Evidence(evidence_id="short", product_id="a", document_id="d", page=1,
                     field_name="short_circuit_protection", text="short circuit hiccup retry",
                     reviewed=True)
    thermal = Evidence(evidence_id="thermal", product_id="a", document_id="d", page=2,
                       field_name="otp", text="thermal shutdown recovery", reviewed=True)
    store.insert_evidence(short); store.insert_evidence(thermal)
    store.save_chunk_embedding("short", "fake", [0, 1])
    store.save_chunk_embedding("thermal", "fake", [1, 0])
    parsed = ParsedQuery(raw_query="DEMO-A-001 短路后怎么恢复", intent=Intent.PART_QA,
                         part_numbers=["DEMO-A-001"], semantic_query="短路后怎么恢复")
    hits = hybrid_search(store, parsed, FakeEmbedder())
    assert [hit.evidence.evidence_id for hit in hits] == ["short"]
    store.close()


def test_rrf_rewards_documents_in_both_lists():
    scores = rrf_fusion(["a", "b"], ["b", "c"])
    assert scores["b"] > scores["a"]
