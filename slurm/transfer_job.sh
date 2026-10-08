#!/bin/bash
#SBATCH --job-name=ws-transfer
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=1-00:00
#SBATCH --output=logs/%x-%j.out
#
# One model for the transfer study: its SeedVille battery and LAB-Bench, against one vLLM server.
# Submitted per model by slurm/submit_transfer.sh (MODEL_ID, OUT and LABBENCH come from there).
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs
source slurm/start_vllm.sh

SV="$OUT/seedville"
B=(--env board --max-actions 200 --max-turns 320 --concurrency 32 --universes ${UNIVERSES:-1 2} --n-train ${NTR:-12} --n-test ${NTE:-10})
run() { python scripts/run_experiment.py "${B[@]}" "$@"; }
run --protocol compgen --conditions none seed --out "$SV/plain"            # test score, memory gain
run --protocol compgen --conditions seed_llm --out "$SV/reflection"        # reflection precision
run --protocol compgen --conditions seed --noise 0.2 --out "$SV/noise"     # noise robustness
run --protocol compgen --conditions seed --skin drug --out "$SV/skin"      # scientific story
if [ -n "${LABBENCH:-}" ]; then
  python scripts/run_labbench.py --data "$LABBENCH" --out "$OUT/labbench.json" ${LB_LIMIT:+--limit $LB_LIMIT}
fi
python -c "import json,sys; sys.path.insert(0,'.'); from worldseeds.transfer import seedville_scores; print(json.dumps(seedville_scores(['$SV']), indent=1))"
