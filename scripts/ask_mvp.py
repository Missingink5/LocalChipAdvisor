"""Command-line entry point for the local MVP service."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Local evidence-bound datasheet advisor")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/mvp/demo-v2/manifest.json")
    parser.add_argument("--query", required=True)
    parser.add_argument("--retrieval-only", action="store_true")
    args = parser.parse_args()
    try:
        from local_chip_advisor.mvp.service import AdvisorService

        result = AdvisorService(args.manifest).ask(args.query, retrieval_only=args.retrieval_only)
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits a structured failure.
        result = {"status": "RETRIEVAL_ERROR", "message": f"本地服务无法启动：{exc}"}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result.get("status") in {"MODEL_ERROR", "RETRIEVAL_ERROR"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
