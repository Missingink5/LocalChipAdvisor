"""Read-only/import smoke checks for the local Python environment."""

from __future__ import annotations

import sqlite3

import chromadb
import fastapi
import httpx
import pymupdf
import streamlit


def main() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE VIRTUAL TABLE docs USING fts5(text)")
    connection.execute("INSERT INTO docs VALUES (?)", ("MPS synchronous buck converter",))
    match_count = connection.execute(
        "SELECT count(*) FROM docs WHERE docs MATCH 'buck'"
    ).fetchone()
    assert match_count is not None and match_count[0] == 1

    client = chromadb.Client()
    assert client.heartbeat() > 0

    with httpx.Client(trust_env=False, timeout=5.0) as http_client:
        ollama_response = http_client.get("http://127.0.0.1:11434/api/version")
        ollama_response.raise_for_status()
        ollama_version = ollama_response.json()["version"]

    print("SQLite FTS5: OK")
    print("Chroma heartbeat: OK")
    print(f"PyMuPDF: {pymupdf.VersionBind}")
    print(f"FastAPI: {fastapi.__version__}")
    print(f"Streamlit: {streamlit.__version__}")
    print(f"Ollama API: {ollama_version} via proxy-independent localhost client")


if __name__ == "__main__":
    main()
