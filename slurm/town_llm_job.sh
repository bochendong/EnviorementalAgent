#!/bin/bash
#SBATCH --job-name=ws-town-llm
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=1-00:00
#SBATCH --output=logs/%x-%j.out
#
# LLM apprentices in the town (money, grand goals, notice board, library) against one vLLM server:
#   1. replays to watch in web/codeworld.html (web/replays/llm.json)
#   2. the experiment: masters / roster / no masters / one apprentice, with money and goals, paid answers on and off
#      sbatch slurm/town_llm_job.sh            (OUT defaults to $WS_STORE/results/town_llm)
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs
source slurm/start_vllm.sh
OUT="${OUT:-$WS_STORE/results/town_llm}"
mkdir -p "$OUT"
python scripts/build_codeworld_web.py --llm --sprints 3 --budget 100 --max-turns 160 --out "$OUT/llm.json"
for AP in 0 4; do
  python scripts/run_codeworld.py --policy llm --save-traces --theme town --walk --money --answer-price $AP \
    --goals banquet prize fund --fund 300 --goal-deadline 3 --universes 1 2 --modules 8 --fns-per-module 6 \
    --capacities 12 --team-sizes 4 --sprints 3 --projects-per-dev 3 --budget 100 --max-turns 160 \
    --variants solo random owners directory --out "$OUT/price$AP"
done
echo "copy $OUT/llm.json to web/replays/llm.json to watch the runs"
