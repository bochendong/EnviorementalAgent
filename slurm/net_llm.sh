#!/bin/bash
#SBATCH --job-name=net-llm
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=0-12:00
#SBATCH --output=logs/%x-%j.out
#
# Serves a Qwen model with vLLM on the job's GPU, then runs LLM teams (netagents/) on network presets.
#   sbatch slurm/net_llm.sh                                   # every difficulty preset, team/solo/nonet
#   PRESETS="math/medium website/heldout-todo" VARIANTS=team SEEDS="0 1 2" sbatch slurm/net_llm.sh
#   MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 sbatch slurm/net_llm.sh
# Also records the town replays of LLM teams (web/replays/llm.json) when REPLAYS=1.
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs

PRESETS="${PRESETS:-codeworld/easy codeworld/medium math/easy math/medium website/easy website/medium molecule/easy molecule/medium}"
VARIANTS="${VARIANTS:-team solo nonet}"
SEEDS="${SEEDS:-0 1 2}"
MAX_TURNS="${MAX_TURNS:-150}"
OUT="${OUT:-$WS_STORE/results/net/$SERVED_NAME/${SLURM_JOB_ID:-local}}"

source slurm/start_vllm.sh
for p in $PRESETS; do
  for v in $VARIANTS; do
    python -m netagents.run --preset "$p" --variant "$v" --policy llm --seeds $SEEDS --max-turns "$MAX_TURNS" \
      --out "$OUT/${p//\//_}/$v" || echo "failed: $p $v"
  done
done
if [ "${REPLAYS:-0}" = "1" ]; then
  python -m netagents.replays --llm --max-turns "$MAX_TURNS" --out "$OUT/llm_replays.json" || true
fi
echo "results in $OUT"
