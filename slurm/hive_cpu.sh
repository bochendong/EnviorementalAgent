#!/bin/bash
#SBATCH --job-name=ws-hive-cpu
#SBATCH --account=def-CHANGE_ME
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=0-12:00
#SBATCH --output=logs/%x-%j.out
#
# Large hives with the heuristic agent (no GPU, no LLM): how shared memory scales from 1 to 1024
# agents in a 64-crop universe (138 hidden laws), with and without faulty agents.
#   sbatch slurm/hive_cpu.sh                       # universes 1 2 3, 3 repeats
#   UNIVERSES="1" REPEATS=1 sbatch slurm/hive_cpu.sh
# Summary: python scripts/analyze_hive.py $SCRATCH/worldseeds/results/hive_cpu --curve
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs
source "$AGENT_VENV/bin/activate"
OUT="${OUT:-$WS_STORE/results/hive_cpu}"
for u in ${UNIVERSES:-1 2 3}; do
  python scripts/run_experiment.py --env board --protocol hive --policy heuristic --conditions seed \
    --n-crops 64 --hive-sizes 1 4 16 64 256 1024 --hive-faulty 0 0.25 --hive-waves 12 \
    --universes "$u" --repeats "${REPEATS:-3}" --n-test 16 --max-actions 200 --out "$OUT/u$u"
done
python scripts/analyze_hive.py "$OUT" --curve
