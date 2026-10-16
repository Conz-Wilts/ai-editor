#!/usr/bin/env bash
# Runs the eval suites (claude plugin eval). Real model calls: needs ANTHROPIC_API_KEY (or a logged-in
# Claude Code). Each case loads the editor from .claude/ (`plugins: ["../../../../.claude"]` in its
# prompt.md: a folder with skills/ and agents/ and no manifest, so its skills show as `.claude:<name>`).
# Extra args go to every run, e.g. --runs 1 or --case start-asks.
# Exit code: 0 when every case passes --threshold (default 0.8), else the first failing exit code.
set -u
cd "$(dirname "$0")/.."
out=${EVAL_OUT:-eval-results}
mkdir -p "$out"
rc=0
for p in creator-teardown ai-editor; do
  claude plugin eval . --eval-dir "tests/evals/$p" \
    --trust-plugin --no-publish --ablation none -j 4 \
    --judge-model "${EVAL_JUDGE:-sonnet}" \
    --threshold "${EVAL_THRESHOLD:-0.8}" \
    --max-cost-usd "${EVAL_MAX_COST:-15}" \
    --json "$out/$p.json" --report "$out/$p.html" "$@" || { r=$?; [ $rc -eq 0 ] && rc=$r; }
done
exit $rc
