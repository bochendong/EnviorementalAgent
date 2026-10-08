#!/bin/bash
#SBATCH --job-name=ws-codeworld
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=1-00:00
#SBATCH --output=logs/%x-%j.out
#
# CodeWorld with LLM developers against one vLLM server; all arguments go to scripts/run_codeworld.py.
#   sbatch slurm/codeworld_job.sh --modules 8 --capacities 8 --out $SCRATCH/worldseeds/results/codeworld/m8
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs
source slurm/start_vllm.sh
python scripts/run_codeworld.py --policy llm --save-traces "$@"
OUT_DIR=results/codeworld
ARGS=("$@")
for ((i = 0; i < ${#ARGS[@]}; i++)); do
  if [ "${ARGS[$i]}" = "--out" ]; then OUT_DIR="${ARGS[$((i + 1))]}"; fi
done
python scripts/analyze_codeworld.py "$OUT_DIR" --costs || true
