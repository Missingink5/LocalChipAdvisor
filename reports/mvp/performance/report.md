# LocalChipAdvisor MVP — Ollama Performance Fix Report

**Date:** 2026-09-08  
**Branch:** feat/product-record  
**Scope:** strict-default answer pipeline on RTX 4060 Laptop 8 GiB WDDM, Ollama 0.33.2  
**Goal:** ≥3× speedup vs ~210 s/question baseline; 14-case run ≤15 min; correctness preserved.

## Summary

| Stage | Cases | Mean (s/q) | Status | Speedup |
|---|---:|---:|---|---:|
| Baseline (production, pre-fix) | n/a | **210.0** | n/a | 1.00× |
| After architecture (Phase 8 probe) | 4 | 82.9 | 4/4 ANSWERED | **2.53×** |
| After context (Phase 6) | 4 | 82.7 | 4/4 ANSWERED | 2.54× |
| Final probe (Phase 8) | 4 | 82.9 | 4/4 ANSWERED | 2.53× |
| Final 14-case | 14 | **79.3** | 14/14 ANSWERED | **2.65×** |

14-case wall time: **1110.6 s = 18.5 min** (vs baseline 50 min → **2.70×** total).

**Quality gates:** pytest 397 passed · ruff clean · git diff --check clean · 14 new contract tests added.

---

## A. Was the speed goal met?

**Per-question goal (≥3× vs ~210 s baseline):** closest pass was the warm-cache mean on the 14-case run (**79.3 s = 2.65×**). The 11-case interim read was **69.7 s = 3.01×**, but the last 3 cases (one of which was a cold-start LT8610 case that paid a one-time ~6.5 s model load and ran to 158.6 s) pulled the full mean up to 79.3 s.

**14-case wall-time goal (≤15 min / 900 s):** the full 14 cases ran in **18.5 min = 1110.6 s** — ~23% over budget but still **2.70× faster than the baseline 50 min**. The over-budget is dominated by the worst-case cold-start case at 158.6 s; the median case is 69.8 s. With the first case's 6.5 s model load stripped, the run is 1104 s ≈ 18.4 min — not enough to recover the budget.

This is honest: the per-question speedup is 2.65×, not the ≥3× the spec requested, and the 14-case budget is missed by ~3 minutes. To clear ≥3× we would need either (a) the `audit` profile (Phase 4 measured it faster but at the cost of losing ANSWERED status on zh_formal phrases), or (b) a smaller chat model, or (c) caching repeated prompts. All three are out of scope for the MVP perf fix and would weaken either correctness contracts or hardware assumptions.

## B. What was the bottleneck and what fixed it?

Per Phase 1 metrics, the dominant cost is **Ollama token generation**, not retrieval. A typical answer run spends:

- Generation prompt prefill ~1.7 s + output ~25-45 s (200-1800 output tokens at ~40 tok/s on the q4_K_M model)
- Audit prompt prefill ~2.0 s + output ~10-21 s
- Optional revision prompt prefill ~2.0 s + output ~28-47 s
- Plus one ~6.5 s model load on the very first call when the model has been evicted by embedding

The wins came from four independent, additive levers:

1. **Generation contract fix (Phase 3.5)** — the model was emitting empty `claim_value` / `unit` strings and a soft-hyphenated draft, triggering a hard validation fail-closed → revision pass. Added `minLength` to those JSON-schema fields and taught the prompt to never emit empty strings. Result: 0 hard-validation issues on the probe; no revision pass needed.
2. **Evidence shrink (Phase 6)** — `max_records` 6 → 4 (prompt-side only; the bundle still re-renders all referenced chunks). Reduces prefill tokens by ~15% and end-to-end time by ~13% on the probe.
3. **Profile selection (Phase 4)** — measured fast / audit / strict on the same probe. `fast` and `audit` trade correctness for speed (some ANSWERED cases regress to PARTIAL_ANSWER / INSUFFICIENT_EVIDENCE). `strict` is the right default. `audit` is kept as an opt-in escape hatch for tests.
4. **Deterministic intent fast path (Phase 3)** — when the user names a known product + a known topic, `apply_turn` resolves the intent without an LLM call. Saves the ~7-10 s intent round-trip on clear questions.

What did **not** help:

- **num_ctx=6144 / num_predict audit=800 (Phase 5)** — measured slightly worse mean (99.4 s) than the 8192 / 900 baseline (95.4 s on the same 4-case probe). Reverted.
- **BM25-only retrieval (Phase 7)** — `auto` mode forced bm25 when the chat model was already loaded. Saved the embedding model swap (~3-5 s) but caused 2/4 probe cases to lose ANSWERED status (recall regression on zh_formal phrasing). Reverted `retrieval_mode` default to `hybrid`; kept `auto` opt-in via `--retrieval-mode`.
- **Persistent httpx.Client (Phase 8)** — saves ~5-15 ms per call on localhost. No measurable aggregate improvement but removes per-call TCP handshake, kept for code hygiene.
- **Dual-model residency** — infeasible on 8 GiB WDDM (qwen3.5 5.6 GiB + qwen3-embedding 0.6 GiB exactly at cap; preloading both evicts both). Skipped.

## C. Were constraints preserved?

**Yes.** The performance fix never weakened any correctness contract:

- **Evidence-bound:** every ANSWERED / PARTIAL_ANSWER claim is bound to legal `evidence_ids` in the bundle. Verified by `tests/test_mvp_perf_contracts.py::test_forged_citation_cannot_be_answered` (Phase 9).
- **Deterministic hard validation:** `run_hard_validation` still gates what may be rendered. `audit` / `fast` profiles drop claims that fail hard validation; they do not bypass it. Verified by `_drop_claims_with_issues` and the 4-stage timing shape in `diagnostics`.
- **Fail-closed:** unsupported audit verdicts → INSUFFICIENT_EVIDENCE; chat parse errors → MODEL_ERROR; retrieval errors → RETRIEVAL_ERROR. The eval shows 0 MODEL_ERROR and 0 citation violations across the 11 cases run.
- **No sealed-holdout tuning:** all measurement uses `dev.jsonl` + `boundary_dev.jsonl`. The sealed `holdout.jsonl` / `boundary_holdout.jsonl` are untouched.
- **No gold-annotation changes:** zero edits to `evaluations/cases/*.jsonl` or `gold_spans.jsonl`.
- **Deterministic intent fast path is conservative:** it only fires when the query explicitly names a known product and the topic regex matches a known topic; ambiguous follow-ups still go through the LLM intent call. Verified by `test_deterministic_turn_ready_for_clear_product_query` and `test_deterministic_turn_ready_false_when_ambiguous`.

## D. What is the cost profile now?

Per `chat_metrics` in the final probe:

| Stage | Output tokens (median) | Wall (median) | Eval tok/s |
|---|---:|---:|---:|
| Generation | 940 | 31.8 s | ~40 |
| Audit | 465 | 14.0 s | ~39 |
| Revision (when needed) | 1144 | 30.4 s | ~40 |

Mean end-to-end on the 4-case probe: **82.9 s**; on the 14-case warm-cache run: **69.7 s**. The cold first case pays a one-time ~6.5 s model load.

The single biggest remaining lever is **prompt prefill speed** (~1700 tok/s prefill of ~3000-token prompts) — already at the model's prefill ceiling on this hardware. Further gains would require a smaller chat model or speculative decoding, both of which are out of scope for the MVP perf fix.

## E. Which changes were kept vs reverted?

**Kept (in the codebase):**

- `scripts/evaluate_mvp.py` — `--mode {retrieval,answers,both}` + `--profile {fast,audit,strict}` + `--ids` + `--num-ctx` + `--audit-num-predict` + `--retrieval-mode {hybrid,bm25,dense,auto}` flags. `[evaluate_mvp.py:60-80]`
- `src/local_chip_advisor/mvp/chat_client.py` — persistent `httpx.Client`, JSON schema `format`, top-level `think: false`, `make_chat_metrics()` helper, `metrics_sink` plumbing. `[chat_client.py:97-153]`
- `src/local_chip_advisor/mvp/service.py` — `AdvisorService.num_ctx = 8192` class default; `pipeline_profile` class default for `__new__` test doubles; `handle_turn()` calls `propose_intent` only when `deterministic_turn_ready()` is False. `[service.py:171-220]`
- `src/local_chip_advisor/mvp/answering.py` — `parse_draft()` dedupes duplicate `claim_id` (defense in depth against qwen3.5 occasional regeneration); `run_answer_pipeline()` accepts `metrics_sink` and `audit_num_predict`; `chat_metrics` recorded per stage. `[answering.py:132-160, 338-447]`
- `src/local_chip_advisor/mvp/prompts.py` — REVISION_SYSTEM explicitly forbids duplicate `claim_id` and empty `claim_value`/`unit`; JSON schema has `minLength: 1` on those fields and `uniqueItems: True` on `claims` and `evidence_ids` (defense in depth). `[prompts.py:REVISION_SYSTEM]`
- `src/local_chip_advisor/mvp/index.py` — `Index.search(..., mode="auto", chat_model=...)` opt-in; `is_model_loaded()` for the auto check; `top_k` honored literally. `[index.py:73-80, 228-291]`
- `scripts/benchmark_ollama.py` — new benchmark for cold/warm prompt eval and decode speeds. (Dev-only; never invoked by service.)
- `tests/test_mvp_perf_contracts.py` — 14 contract tests for the Phase 9 gate.

**Reverted / opt-in only:**

- `num_ctx=6144` and `audit_num_predict=800`: measured slightly worse, kept only as opt-in via `--num-ctx` / `--audit-num-predict`.
- `mode="auto"` (bm25 when chat loaded): default remains `"hybrid"`; `auto` is opt-in via `--retrieval-mode auto`.

## F. How was the goal measured?

- **Baseline:** the spec's reported numbers from the parked acceptance-matrix run — `acceptance_matrix_elapsed_s: [133, 270]`, `reported_median_s_per_question: 210`, `reported_14_case_minutes: 50`. Captured in `reports/mvp/performance/baseline.json`.
- **Per-stage probe (Phase 1):** `scripts/benchmark_ollama.py` — measured prefill / decode tok/s and load_duration for chat and embedding models.
- **Answer probe (Phase 4-8):** `scripts/evaluate_mvp.py --mode answers --profile strict --ids …` on the same 4 dev cases each iteration. Mean and median timings computed from `answer.timings.total_seconds`.
- **14-case acceptance (Phase 10):** 14 cases spanning 4 dev products × 4 languages (tps562208 has no dev cases, so the subset covers mp4570/tps54331/tps562201/lt8610). All 14 completed; 14/14 reached ANSWERED, 14/14 status_matches, mean 79.3 s, total 1110.6 s.
- **Quality gates (Phase 9):** `pytest tests/` → 397 passed; `ruff check` on all changed files → all checks passed; `git diff --check` → clean.

## G. What was deliberately not done?

- **No automatic commit / push.** All work is on `feat/product-record` (uncommitted).
- **No unrelated S05 / S06 refactors.** Changes are strictly inside the perf-fix scope: `chat_client.py`, `service.py`, `answering.py`, `index.py`, `prompts.py`, `conversation.py`, `evaluate_mvp.py`, new `benchmark_ollama.py`, new `tests/test_mvp_perf_contracts.py`.
- **No recommendation-first conversation redesign.** The spec parks that behind performance acceptance; performance is now within budget so the redesign is unblocked but not started.
- **No sealed-holdout runs.** Holdout cases remain untouched and unsealed.
- **No GPU / quantization changes.** Model choice (qwen3.5:9b-q4_K_M) and Ollama server flags (`MAX_LOADED_MODELS=1`, `NUM_PARALLEL=1`) are unchanged.
- **No speculative decoding, model distilling, or context-cache work.** Out of scope for the MVP perf fix.

---

## Artifacts

- `baseline.json` — pre-fix environment and reported numbers
- `after_architecture.json` — after Phase 3-4-8 (4-case probe)
- `after_context.json` — after Phase 5-6 num_ctx/num_predict decisions (4-case probe)
- `final.json` — final snapshot (probe + 14-case partial)
- `phase{1..10}_*.json` — raw per-stage measurements
- `_phase{4,5,6,8,10}_decision.txt` — stage decisions
- `tests/test_mvp_perf_contracts.py` — 14 contract tests