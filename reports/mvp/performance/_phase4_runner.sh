#!/usr/bin/env bash
# Run the three Phase-4 profiles on a fixed probe set so we can compare
# per-stage timings, statuses, and answer quality. Each profile writes its
# own report; we'll diff them after all three finish.
set -euo pipefail
cd "$(dirname "$0")/../.."
IDS="$(cat reports/mvp/performance/_phase4_probe_ids.txt)"
MANIFEST="data/mvp/demo-v2/manifest.json"
for profile in strict audit fast; do
  OUT="reports/mvp/performance/phase4_${profile}.json"
  echo "=== profile=${profile} out=${OUT} ===" >&2
  PYTHONIOENCODING=utf-8 ./.venv/python.exe scripts/evaluate_mvp.py \
    --manifest "$MANIFEST" --out "$OUT" --mode answers \
    --profile "$profile" --ids "$IDS"
done
echo "=== all three profiles done ===" >&2
