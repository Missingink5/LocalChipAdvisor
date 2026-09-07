"""CLI entry point for the conversational, evidence-bound MVP advisor.

Usage:
    python scripts/ask_mvp.py --query "MP4570 太热会自己停吗？"
    python scripts/ask_mvp.py --interactive
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_chip_advisor.mvp.contracts import (
    ClarificationRequest, UserTurn, gen_id,
)
from local_chip_advisor.mvp.conversation import new_session_state
from local_chip_advisor.mvp.service import AdvisorService


def _print_result(result_dict: dict) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result_dict, ensure_ascii=False, indent=2, default=str))


def _render_for_terminal(result) -> None:
    status = result.status
    answer = result.answer_text or result.message
    print(f"\n[{status}] {answer}")
    for gap in result.unanswered_scopes:
        print(f"  gap: {gap.scope_zh}")
    if result.clarification:
        c = result.clarification
        print(f"  clarification: {c.question}")
        for opt in c.options:
            print(f"    option: {opt.label} (id={opt.option_id})")
    for cite in result.citations:
        print(f"  source: {cite.marker} chunk={cite.chunk_id} pages={cite.page_start}-{cite.page_end}")


def single_shot(manifest: Path, query: str, retrieval_only: bool) -> int:
    try:
        service = AdvisorService(manifest)
        result_dict = service.ask(query, retrieval_only=retrieval_only)
    except Exception as exc:  # noqa: BLE001
        result_dict = {"status": "RETRIEVAL_ERROR",
                       "message": f"本地服务无法启动：{type(exc).__name__}: {exc}"}
    _print_result(result_dict)
    return 1 if result_dict.get("status") in {"MODEL_ERROR", "RETRIEVAL_ERROR"} else 0


def interactive(manifest: Path) -> int:
    service = AdvisorService(manifest)
    session_id = gen_id("cli")
    state = new_session_state(session_id)
    print("进入交互模式。输入问题，模型将给出中文回答或追问；输入 /new 清空会话，"
          "/exit 退出。")
    while True:
        try:
            raw = input("\n[用户] ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出交互。")
            return 0
        if not raw:
            continue
        if raw == "/exit":
            print("退出交互。")
            return 0
        if raw == "/new":
            session_id = gen_id("cli")
            state = new_session_state(session_id)
            print("[系统] 已开启新会话。")
            continue
        user_turn = UserTurn(turn_id=gen_id("turn"), text=raw)
        state, result = service.handle_turn(state, user_turn)
        _render_for_terminal(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local evidence-bound datasheet advisor")
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "data/mvp/demo-v2/manifest.json")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="Run a single query and exit")
    group.add_argument("--interactive", action="store_true",
                       help="Start an interactive multi-turn REPL")
    parser.add_argument("--retrieval-only", action="store_true")
    args = parser.parse_args()
    args.manifest = args.manifest.resolve()
    if args.interactive:
        return interactive(args.manifest)
    return single_shot(args.manifest, args.query, args.retrieval_only)


if __name__ == "__main__":
    raise SystemExit(main())
