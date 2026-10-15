#!/bin/bash
#SBATCH --job-name=net-smoke
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=0-00:45
#SBATCH --output=logs/%x-%j.out
#
# A few minutes before any real run (netagents/smoke.py): does the vLLM server start, does it answer every
# kind of request the designs make (plain chat, tools required / auto, thinking off, JSON, a long prompt),
# and do one sas and one centralized run go through without model errors? Prints a table; writes
# smoke.json with every error in full. Exit status 1 if anything failed.
#   sbatch slurm/net_smoke.sh            (run_all.sh STAGE=smoke submits it with the right accounts)
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs

OUT="${OUT:-$WS_STORE/results/net/smoke/$SERVED_NAME/${SLURM_JOB_ID:-local}}"
source slurm/start_vllm.sh
echo "vLLM: $(grep -m1 -i 'vllm api server version\|version' "$SERVER_LOG" || true)"
python -m netagents.smoke --out "$OUT"
