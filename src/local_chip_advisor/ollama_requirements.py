"""Ollama adapter for structured requirement extraction."""

import httpx

from local_chip_advisor.requirements import (
    RequirementParsePayload,
    parse_requirement_payload_json,
)


_SYSTEM_PROMPT = """Extract only explicitly stated Buck converter requirements.

Do not invent missing values.
Use null for information that is not explicitly provided.
Return only data matching the supplied JSON schema.
Do not set user confirmation or alter the user's original request.
"""


class OllamaRequirementParser:
    """Parse natural-language requirements through Ollama structured output."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://localhost:11434",
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client()

    def parse(
        self,
        raw_request: str,
    ) -> RequirementParsePayload:
        response = self._client.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": _SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": raw_request,
                    },
                ],
                "format": RequirementParsePayload.model_json_schema(),
                "stream": False,
                "options": {
                    "temperature": 0,
                },
            },
        )
        response.raise_for_status()

        data = response.json()
        response_text = data["message"]["content"]

        return parse_requirement_payload_json(response_text)
