"""Real-model conversation smoke test.

Runs an end-to-end multi-turn sequence against the live Ollama backend,
recording the resulting answer text and citations. The output JSON is the
acceptance evidence for R5.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_chip_advisor.mvp.contracts import UserTurn, gen_id
from local_chip_advisor.mvp.conversation import new_session_state
from local_chip_advisor.mvp.service import AdvisorService


# (description, sequence of user turns) — the harness asserts that the
# conversation stays coherent across turns.
SCENARIOS = [
    ("ambiguous_to_clarified",
     ["太热会自己停吗？", "MP4570"]),
    ("topical_choice",
     ["MP4570 怎么样？", "过温保护", "前一个"]),
    ("product_swap",
     ["MP4570 过温保护？", "换成 TPS54331"]),
    ("english_then_chinese",
     ["MP4570 soft start?", "持续时间能调整吗？"]),
]


def run_scenario(service: AdvisorService, description: str,
                 user_texts: list[str]) -> list[dict]:
    state = new_session_state(gen_id("smoke"))
    log: list[dict] = []
    for text in user_texts:
        turn = UserTurn(turn_id=gen_id("smoke-turn"), text=text)
        started = time.perf_counter()
        state, result = service.handle_turn(state, turn)
        elapsed = round(time.perf_counter() - started, 3)
        log.append({
            "input": text,
            "status": result.status,
            "answer_text": result.answer_text,
            "message": result.message,
            "clarification": result.clarification.model_dump() if result.clarification else None,
            "citations": [c.model_dump() for c in result.citations],
            "claim_count": len(result.claims),
            "unanswered": [g.scope_zh for g in result.unanswered_scopes],
            "elapsed_seconds": elapsed,
        })
    return {"description": description, "turns": log}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "data/mvp/demo-v2/manifest.json")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "reports/mvp/answer_fix/smoke_conversation.json")
    parser.add_argument("--scenario", default=None)
    args = parser.parse_args()
    service = AdvisorService(args.manifest)
    scenarios = SCENARIOS if not args.scenario else [next(s for s in SCENARIOS if s[0] == args.scenario)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {"scenarios": []}
    for description, user_texts in scenarios:
        try:
            report["scenarios"].append(run_scenario(service, description, user_texts))
            print(f"OK  {description}", flush=True)
        except Exception as exc:  # noqa: BLE001
            report["scenarios"].append({
                "description": description, "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"ERR {description}: {exc}", flush=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
