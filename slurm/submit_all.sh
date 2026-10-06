#!/bin/bash
# Submit the full study: one GPU job per (protocol, universe) so they run in parallel.
#   bash slurm/submit_all.sh            # default model (Qwen3-8B)
#   MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/submit_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source slurm/env.sh
OUT="${OUT:-$WS_STORE/results/$SERVED_NAME}"
UNIVERSES="${UNIVERSES:-0 1 2 3 4}"
REPEATS="${REPEATS:-2}"
COMMON=(--repeats "$REPEATS" --concurrency 32 --max-actions 50 --max-turns 120 --save-traces)

for u in $UNIVERSES; do
  # H4/RQ8 + H3: compositional generalisation, all memory conditions, zoom vs flat
  sbatch --job-name="ws-compgen-u$u" slurm/serve_and_run.sh --protocol compgen \
    --conditions none trajectory retrieval seed seed_llm oracle --views zoom flat \
    --universes "$u" --n-train 24 --n-test 16 "${COMMON[@]}" --out "$OUT/compgen/u$u"
  # H1/RQ1: persistent world vs reset
  sbatch --job-name="ws-persist-u$u" slurm/serve_and_run.sh --protocol persistence \
    --conditions none retrieval seed --universes "$u" --n-test 8 "${COMMON[@]}" --out "$OUT/persistence/u$u"
  # H5/RQ7: law shift
  sbatch --job-name="ws-shift-u$u" slurm/serve_and_run.sh --protocol law_shift \
    --conditions none seed --decay 0.7 --universes "$u" --n-train 16 "${COMMON[@]}" --out "$OUT/law_shift/u$u"
  # RQ9: shared vs independent seeds
  sbatch --job-name="ws-multi-u$u" slurm/serve_and_run.sh --protocol multiagent \
    --conditions seed --n-agents 4 --universes "$u" --n-train 16 --n-test 12 "${COMMON[@]}" --out "$OUT/multiagent/u$u"
  # RQ10: mutation curriculum vs uniform
  sbatch --job-name="ws-curr-u$u" slurm/serve_and_run.sh --protocol curriculum \
    --conditions seed --universes "$u" --n-train 24 --n-test 12 "${COMMON[@]}" --out "$OUT/curriculum/u$u"
done
echo "submitted. results -> $OUT ; summarise with: python scripts/analyze.py $OUT --curve"
