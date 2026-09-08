"""Ollama cold/warm/thrash benchmark with full per-call metrics.

Measures the five residency scenarios that matter for the MVP question path:

  1. cold chat          — chat model not loaded (load_duration > 0)
  2. warm chat          — chat model resident (load_duration ~ 0)
  3. embedding          — query embedding via /api/embed (as Index.search does)
  4. embedding -> chat  — first thrash direction: does chat have to reload?
  5. chat -> embed -> chat — full thrash loop (MAX_LOADED_MODELS=1 forces evict)

Each scenario prints stage/model/wall/load/prompt/output/tok-s and the
post-scenario `ollama ps` residency (size, size_vram, processor, context).

The default num_ctx reproduces the production ChatClient value (8192) so the
baseline reflects what the MVP actually requests today. Use --num-ctx 4096
for the Phase 5 comparison.
"""
from __future__ import annotations

import argparse
import json
import time

import httpx

from local_chip_advisor.mvp.chat_client import ChatClient, make_chat_metrics

BASE_URL = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "qwen3-embedding:0.6b"
QUERY_PREFIX = "Instruct: Retrieve relevant semiconductor datasheet passages for the query.\nQuery: "
METRIC_KEYS = ("stage", "wall_seconds", "load_seconds", "prompt_tokens",
               "prompt_tokens_per_second", "output_tokens", "output_tokens_per_second")


def _emit(metrics: dict) -> None:
    print(" | ".join(f"{k}={metrics.get(k)}" for k in METRIC_KEYS), flush=True)


def _ps(client: httpx.Client) -> None:
    running = client.get("/api/ps").json().get("models", [])
    if not running:
        print("  ps: (nothing loaded)", flush=True)
        return
    for model in running:
        print(f"  ps: {model['name']} size={model.get('size')} "
              f"size_vram={model.get('size_vram')} processor={model.get('processor')} "
              f"context={model.get('context_size')}", flush=True)


def _embed(client: httpx.Client, query: str) -> dict:
    started = time.perf_counter()
    response = client.post(
        "/api/embed",
        json={"model": EMBEDDING_MODEL, "input": query,
              "truncate": False, "keep_alive": "30m"},
    )
    response.raise_for_status()
    payload = response.json()
    wall = round(time.perf_counter() - started, 4)
    embed = payload.get("embeddings", [None])[0]
    return {
        "stage": "embedding",
        "model": EMBEDDING_MODEL,
        "wall_seconds": wall,
        "load_seconds": make_chat_metrics(payload, stage="embedding",
                                          model=EMBEDDING_MODEL, wall_seconds=wall,
                                          num_ctx=0, num_predict=0,
                                          temperature=0.0)["load_seconds"],
        "dimension": len(embed) if embed else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-ctx", type=int, default=8192,
                        help="num_ctx sent per chat request (production default 8192)")
    parser.add_argument("--queries", type=int, default=1,
                        help="number of repeat warm-chat rounds (default 1)")
    parser.add_argument("--json", type=str, default=None,
                        help="optional file to write full per-call metrics as JSON")
    args = parser.parse_args()

    chat = ChatClient(model="qwen3.5:9b-q4_K_M", num_ctx=args.num_ctx)
    samples: list[dict] = []

    def sample(metrics: dict) -> None:
        _emit(metrics)
        samples.append(metrics)

    with httpx.Client(base_url=BASE_URL, timeout=300.0, trust_env=False) as client:
        query = QUERY_PREFIX + "MP4570 过温关断在多少度触发、多少度恢复？"
        # 1. cold chat
        print(f"[1] cold chat (num_ctx={args.num_ctx})", flush=True)
        chat.chat("Reply LOCAL_OK only.",
                  {"probe": "measure cold start"}, json_schema={
                      "type": "object",
                      "properties": {"ok": {"type": "boolean"}},
                      "required": ["ok"]},
                  num_predict=16, stage="cold_chat", metrics_sink=sample)
        _ps(client)
        # 2. warm chat
        for i in range(args.queries):
            print(f"[2.{i}] warm chat", flush=True)
            chat.chat("Reply LOCAL_OK only.",
                      {"probe": "measure warm start"}, json_schema={
                          "type": "object",
                          "properties": {"ok": {"type": "boolean"}},
                          "required": ["ok"]},
                      num_predict=16, stage="warm_chat", metrics_sink=sample)
        _ps(client)
        # 3. embedding (cold if never loaded)
        print("[3] embedding", flush=True)
        samples.append(_embed(client, query))
        _emit(samples[-1])
        _ps(client)
        # 4. embedding -> chat (does chat reload?)
        print("[4] embedding -> chat", flush=True)
        chat.chat("Reply LOCAL_OK only.",
                  {"probe": "measure reload after embedding"}, json_schema={
                      "type": "object",
                      "properties": {"ok": {"type": "boolean"}},
                      "required": ["ok"]},
                  num_predict=16, stage="embed_to_chat", metrics_sink=sample)
        _ps(client)
        # 5. chat -> embedding -> chat (full loop)
        print("[5] chat -> embedding -> chat", flush=True)
        samples.append(_embed(client, query))
        _emit(samples[-1])
        chat.chat("Reply LOCAL_OK only.",
                  {"probe": "measure second reload"}, json_schema={
                      "type": "object",
                      "properties": {"ok": {"type": "boolean"}},
                      "required": ["ok"]},
                  num_predict=16, stage="chat_embed_chat", metrics_sink=sample)
        _ps(client)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(samples, handle, ensure_ascii=False, indent=2)
        print(f"Wrote {args.json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
