#!/bin/bash
# The transfer study: does SeedVille rank models the way real benchmarks do? One GPU job per model
# (slurm/transfer_job.sh): a SeedVille battery (plain, LLM reflection, noise, drug skin) and LAB-Bench.
#   # once, on a login node: the weights of every model, and LAB-Bench
#   for m in Qwen/Qwen3-8B Qwen/Qwen3-14B Qwen/Qwen3-30B-A3B-FP8; do MODEL_ID=$m bash slurm/setup_nibi.sh; done
#   hf download futurehouse/lab-bench --repo-type dataset --local-dir $SCRATCH/worldseeds/data/lab-bench
#   bash slurm/submit_transfer.sh
#   MODELS="Qwen/Qwen3-8B Qwen/Qwen3-14B" LB_LIMIT=200 bash slurm/submit_transfer.sh   # smaller
# Then fill docs/transfer_study.example.json (copy it next to the results; add other benchmarks' scores and a
# covariate) and run: python scripts/transfer_analysis.py $SCRATCH/worldseeds/results/transfer/study.json
set -euo pipefail
cd "$(dirname "$0")/.."
source slurm/env.sh
MODELS="${MODELS:-Qwen/Qwen3-8B Qwen/Qwen3-14B Qwen/Qwen3-30B-A3B-FP8 Qwen/Qwen3-32B-FP8}"
ROOT="${ROOT:-$WS_STORE/results/transfer}"
export LABBENCH="${LABBENCH:-$WS_STORE/data/lab-bench}"
[ -d "$LABBENCH" ] || { echo "LAB-Bench not found at $LABBENCH (download it on a login node, see above)"; LABBENCH=""; }
for m in $MODELS; do
  name=$(basename "$m" | tr '[:upper:]' '[:lower:]')
  MODEL_ID="$m" MODEL_DIR="$WS_STORE/models/$(basename "$m")" SERVED_NAME="$name" OUT="$ROOT/$name" \
    sbatch --job-name="ws-transfer-$name" --export=ALL slurm/transfer_job.sh
done
echo "results -> $ROOT/<model>/ ; then: python scripts/transfer_analysis.py <study.json>"
