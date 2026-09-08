
import json

import httpx

from local_chip_advisor.llm import DeepSeekChatClient, QueryParsingError
from local_chip_advisor.models import Constraint, Evidence, Intent, Operator, ParsedQuery, Product
from local_chip_advisor.pipeline import ChipAdvisor
from local_chip_advisor.store import ChipStore


class FakeChat:
    parse_calls = 0
    answer_calls = 0

    def parse_query(self, query):
        self.parse_calls += 1
        return ParsedQuery(raw_query=query, intent=Intent.PART_SELECTION, constraints=[
            Constraint(field="iout_max_a", operator=Operator.GTE, value=5)
        ])

    def generate_grounded_answer(self, query, evidence, structured_facts=None):
        self.answer_calls += 1
        return "短路时进入保护并在故障解除后重试。[E1]"


class NoEmbed:
    model = "fake"
    calls = 0
    def embed_texts(self, texts):
        self.calls += 1
        return [[1.0, 0.0]]


def make_advisor(tmp_path):
    store = ChipStore(tmp_path / "test.db")
    store.init_db()
    store.upsert_product(Product(product_id="a", part_number="DEMO-A-001", category="DC-DC",
                                 topology="Buck", vin_max_v=36, iout_max_a=5, reviewed=True))
    store.insert_evidence(Evidence(evidence_id="e1", product_id="a", document_id="d1",
                                   page=3, section="Protection", text="short circuit protection",
                                   reviewed=True))
    return store, FakeChat(), NoEmbed()


def test_routing_and_api_budgets(tmp_path):
    store, chat, embedder = make_advisor(tmp_path)
    advisor = ChipAdvisor(store, chat, embedder)
    selection = advisor.answer("找一个5A芯片")
    assert selection.intent == Intent.PART_SELECTION
    assert chat.parse_calls == 1 and chat.answer_calls == 0 and embedder.calls == 0
    exact = advisor.answer("DEMO-A-001最大输入电压是多少？")
    assert "36" in exact.answer
    assert chat.parse_calls == 1 and chat.answer_calls == 0 and embedder.calls == 0
    technical = advisor.answer("DEMO-A-001短路后如何保护？")
    assert technical.evidence and chat.answer_calls == 1
    compare = advisor.answer("比较 DEMO-A-001 和 DEMO-B-001")
    assert compare.intent == Intent.PART_COMPARE and chat.parse_calls == 1
    store.close()


def test_no_evidence_does_not_call_answer_model(tmp_path):
    store = ChipStore(tmp_path / "empty.db"); store.init_db()
    chat = FakeChat()
    result = ChipAdvisor(store, chat, None).answer("MPQ9999短路后如何保护？")
    assert "没有找到足够" in result.answer and chat.answer_calls == 0
    store.close()


def test_invalid_json_retries_once():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "bad"}, "finish_reason": "stop"}]})
    client = DeepSeekChatClient(api_key="fake", transport=httpx.MockTransport(handler))
    try:
        try:
            client.parse_query("q")
        except QueryParsingError:
            pass
        assert calls == 2
    finally:
        client.close()


def test_deepseek_parser_request_is_small_json_and_thinking_disabled():
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        content = ParsedQuery(raw_query="q", intent=Intent.PART_SELECTION).model_dump_json()
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        })

    client = DeepSeekChatClient(api_key="fake", transport=httpx.MockTransport(handler))
    try:
        client.parse_query("q")
    finally:
        client.close()
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["max_tokens"] == 600
    assert captured["stream"] is False
