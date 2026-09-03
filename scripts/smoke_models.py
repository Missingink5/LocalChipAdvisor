"""Exercise the configured local embedding and chat models without system proxies."""

from __future__ import annotations

import time

import httpx


BASE_URL = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "qwen3-embedding:0.6b"
CHAT_MODEL = "qwen3.5:9b-q4_K_M"


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=180.0, trust_env=False) as client:
        tags_response = client.get("/api/tags")
        tags_response.raise_for_status()
        installed = {model["name"] for model in tags_response.json()["models"]}
        assert EMBEDDING_MODEL in installed, f"missing model: {EMBEDDING_MODEL}"
        assert CHAT_MODEL in installed, f"missing model: {CHAT_MODEL}"

        embed_start = time.perf_counter()
        embed_response = client.post(
            "/api/embed",
            json={
                "model": EMBEDDING_MODEL,
                "input": "工业 24 V 输入、5 V 3 A 输出的同步降压转换器",
                "keep_alive": 0,
            },
        )
        embed_response.raise_for_status()
        embeddings = embed_response.json()["embeddings"]
        assert len(embeddings) == 1 and len(embeddings[0]) > 0
        embed_seconds = time.perf_counter() - embed_start

        chat_start = time.perf_counter()
        chat_response = client.post(
            "/api/chat",
            json={
                "model": CHAT_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return exactly LOCAL_OK and no other text.",
                    },
                    {"role": "user", "content": "Run the local model smoke test."},
                ],
                "stream": False,
                "keep_alive": "5m",
                "options": {"temperature": 0, "num_ctx": 4096},
            },
        )
        chat_response.raise_for_status()
        content = chat_response.json()["message"]["content"].strip()
        assert content == "LOCAL_OK", f"unexpected chat response: {content!r}"
        chat_seconds = time.perf_counter() - chat_start

        process_response = client.get("/api/ps")
        process_response.raise_for_status()
        running_models = process_response.json()["models"]

    print(f"Installed models: {', '.join(sorted(installed))}")
    print(f"Embedding dimension: {len(embeddings[0])}")
    print(f"Embedding cold-call time: {embed_seconds:.2f}s")
    print(f"Chat cold-call time: {chat_seconds:.2f}s")
    for model in running_models:
        print(
            "Running model: "
            f"{model['name']}, size={model['size']}, size_vram={model.get('size_vram', 'unknown')}"
        )


if __name__ == "__main__":
    main()
