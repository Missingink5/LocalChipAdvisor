"""Build the isolated MVP index using real local Ollama embeddings."""
import argparse
from pathlib import Path

from local_chip_advisor.mvp.index import MODEL, build


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=root / "data/processed/knowledge.sqlite3")
    parser.add_argument("--output", type=Path, default=root / "data/mvp/demo-v2")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()
    print(build(args.database, args.output, args.base_url, args.model))


if __name__ == "__main__":
    main()
