#!/bin/bash
#SBATCH --job-name=net-fidelity
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=0-08:00
#SBATCH --output=logs/%x-%j.out
#
# Serves a Qwen model with vLLM, then checks a ported design against the authors' own code on their own
# benchmark (netagents/fidelity.py): multiagent debate on GSM8K.
#   sbatch slurm/net_fidelity.sh                      # N=100
#   N=300 MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 sbatch slurm/net_fidelity.sh
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs

N="${N:-100}"
OUT="${OUT:-$WS_STORE/results/net/fidelity/$SERVED_NAME/${SLURM_JOB_ID:-local}}"

source slurm/start_vllm.sh
python -m netagents.fidelity --check debate --n "$N" --out "$OUT" ${ARMS:+--arms $ARMS}
echo "results in $OUT"
