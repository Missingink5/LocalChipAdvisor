"""Zero-cost environment checks; optional one-request DeepSeek smoke test."""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from local_chip_advisor.llm import DeepSeekChatClient, config_value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deepseek-smoke", action="store_true")
    args = parser.parse_args()
    ok = True
    print(f"Python 3.11: {'OK' if sys.version_info[:2] == (3, 11) else 'FAIL'}")
    ok &= sys.version_info[:2] == (3, 11)
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE test_fts USING fts5(text)")
        print("SQLite FTS5: OK")
    except sqlite3.Error as exc:
        print(f"SQLite FTS5: FAIL ({exc})")
        ok = False
    with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
        writable = Path(temp_dir).exists()
        print(f"Database directory writable: {'OK' if writable else 'FAIL'}")
        ok &= writable
    base = (config_value("LCA_EMBED_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/")
    model = config_value("LCA_EMBED_MODEL", "qwen3-embedding:0.6b") or "qwen3-embedding:0.6b"
    try:
        with httpx.Client(timeout=3, trust_env=False) as client:
            response = client.get(base + "/api/tags")
            response.raise_for_status()
            names = {item.get("name") for item in response.json().get("models", [])}
        installed = model in names or any(name and name.startswith(model + ":") for name in names)
        print(f"Ollama: OK; embedding model: {'OK' if installed else 'MISSING'} ({model})")
        ok &= installed
    except httpx.HTTPError:
        print("Ollama: UNREACHABLE（先启动 Ollama；不会删除数据）")
        ok = False
    key_present = bool(config_value("DEEPSEEK_API_KEY"))
    print(f"DEEPSEEK_API_KEY: {'SET' if key_present else 'MISSING'}")
    ok &= key_present
    if args.deepseek_smoke:
        if not key_present:
            print("DeepSeek smoke: SKIPPED（缺少 API key）")
            return 1
        client = DeepSeekChatClient()
        try:
            print(f"DeepSeek smoke: {'OK' if client.smoke() else 'UNEXPECTED RESPONSE'}")
        finally:
            client.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
