#!/bin/bash
#SBATCH --job-name=net-eval
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=1-00:00
#SBATCH --output=logs/%x-%j.out
#
# Serves a Qwen model with vLLM, then runs the published agent designs (netagents/designs.py) on a test
# suite (netagents/testset.py) with matched compute.
#   sbatch slurm/net_eval.sh                                   # SUITE=dev, every design
#   SUITE=test DESIGNS="react centralized decentralized" sbatch slurm/net_eval.sh
#   SUITE=scaling MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 sbatch slurm/net_eval.sh
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs

SUITE="${SUITE:-dev}"
DESIGNS="${DESIGNS:-all}"
OUT="${OUT:-$WS_STORE/results/net/eval/$SERVED_NAME/$SUITE/${SLURM_JOB_ID:-local}}"

source slurm/start_vllm.sh
python -m netagents.evaluate --suite "$SUITE" --designs $DESIGNS --out "$OUT"
echo "results in $OUT"
