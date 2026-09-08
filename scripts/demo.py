"""Minimal command-line demo."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from local_chip_advisor.llm import DeepSeekChatClient, OllamaEmbeddingClient
from local_chip_advisor.pipeline import ChipAdvisor
from local_chip_advisor.store import ChipStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--db", default=str(ROOT / "data" / "chip_advisor.db"))
    args = parser.parse_args()
    store = ChipStore(args.db)
    store.init_db()
    chat = DeepSeekChatClient()
    embedder = OllamaEmbeddingClient()
    try:
        result = ChipAdvisor(store, chat, embedder).answer(args.query)
        print(result.model_dump_json(indent=2))
    finally:
        embedder.close()
        chat.close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
