"""Ollama adapter tests for structured requirement extraction."""

import json

import httpx

from local_chip_advisor.ollama_requirements import (
    OllamaRequirementParser,
)
from local_chip_advisor.requirements import (
    RequirementParsePayload,
)


def test_ollama_requirement_parser_uses_structured_chat_output() -> None:
    raw_request = (
        "??18?30V???24V???5V?"
        "????2.5A???3A??10ms"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/chat"

        body = json.loads(request.content)

        assert body["model"] == "test-model"
        assert body["stream"] is False
        assert body["think"] is False
        assert body["format"] == RequirementParsePayload.model_json_schema()

        schema_text = json.dumps(
            RequirementParsePayload.model_json_schema(),
            ensure_ascii=False,
        )
        assert schema_text in body["messages"][0]["content"]

        assert body["options"]["temperature"] == 0

        assert body["messages"][-1] == {
            "role": "user",
            "content": raw_request,
        }

        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "vin_min_v": 18,
                            "vin_nominal_v": 24,
                            "vin_max_v": 30,
                            "vout_target_v": 5,
                            "iout_continuous_a": 2.5,
                            "iout_peak_a": 3,
                            "peak_duration_ms": 10,
                        }
                    ),
                }
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
    )

    parser = OllamaRequirementParser(
        model="test-model",
        base_url="http://localhost:11434",
        client=client,
    )

    payload = parser.parse(raw_request)

    assert payload.vin_min_v == 18
    assert payload.vin_nominal_v == 24
    assert payload.vin_max_v == 30
    assert payload.vout_target_v == 5
    assert payload.iout_continuous_a == 2.5
    assert payload.iout_peak_a == 3
    assert payload.peak_duration_ms == 10


def test_default_ollama_client_ignores_environment_proxy(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "ALL_PROXY",
        "socks5://127.0.0.1:1080",
    )
    monkeypatch.setenv(
        "HTTP_PROXY",
        "socks5://127.0.0.1:1080",
    )
    monkeypatch.setenv(
        "HTTPS_PROXY",
        "socks5://127.0.0.1:1080",
    )

    OllamaRequirementParser(
        model="test-model",
    )


def test_default_ollama_client_uses_extended_read_timeout(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    real_client = httpx.Client

    def fake_client(*args: object, **kwargs: object) -> httpx.Client:
        captured.update(kwargs)
        return real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200)
            ),
            trust_env=False,
        )

    monkeypatch.setattr(httpx, "Client", fake_client)

    OllamaRequirementParser(
        model="test-model",
    )

    timeout = captured["timeout"]

    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == 120.0
    assert timeout.connect == 5.0
