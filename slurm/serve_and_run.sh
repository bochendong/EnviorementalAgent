#!/bin/bash
#SBATCH --job-name=worldseeds
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=0-12:00
#SBATCH --output=logs/%x-%j.out
#
# Starts a vLLM OpenAI-compatible server for a free Qwen model on the allocated GPU,
# waits for it, then runs one experiment against it. All arguments are forwarded to
# scripts/run_experiment.py, e.g.
#   sbatch slurm/serve_and_run.sh --protocol compgen --conditions none retrieval seed oracle \
#          --universes 0 1 2 --views zoom flat --out $SCRATCH/worldseeds/results/compgen
# Override the model per job:  MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 sbatch slurm/serve_and_run.sh ...
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs

source slurm/start_vllm.sh
python scripts/run_experiment.py "$@"
OUT_DIR=results/run
ARGS=("$@")
for ((i = 0; i < ${#ARGS[@]}; i++)); do
  if [ "${ARGS[$i]}" = "--out" ]; then OUT_DIR="${ARGS[$((i + 1))]}"; fi
done
python scripts/analyze.py "$OUT_DIR" || true
