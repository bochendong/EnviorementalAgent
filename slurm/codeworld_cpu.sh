#!/bin/bash
#SBATCH --job-name=ws-codeworld-cpu
#SBATCH --account=def-CHANGE_ME
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=0-04:00
#SBATCH --output=logs/%x-%j.out
#
# CodeWorld with heuristic developers: the phase diagram (world size x capacity) and team scaling.
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs
source "$AGENT_VENV/bin/activate"
OUT="${OUT:-$WS_STORE/results/codeworld_cpu}"
python scripts/run_codeworld.py --universes 1 2 3 4 5 --modules 4 8 16 32 64 --capacities 8 16 32 --team-sizes 4 \
  --sprints 10 --out "$OUT/phase"
python scripts/run_codeworld.py --universes 1 2 3 4 5 --modules 32 --capacities 16 --team-sizes 2 4 8 16 32 \
  --sprints 10 --variants solo owners directory random pooled --out "$OUT/scale"
python scripts/analyze_codeworld.py "$OUT/phase" --costs
python scripts/analyze_codeworld.py "$OUT/scale" --costs
# the town (8 workshops x 6 machines) and three districts, with and without walking / one-visit questions
for W in "" "--walk"; do
  python scripts/run_codeworld.py --theme town $W --universes 1 2 3 4 5 --modules 8 --fns-per-module 6 --capacities 12 \
    --team-sizes 4 --sprints 10 --variants solo random owners directory pooled --out "$OUT/town$W"
  for B in "" "--batch"; do
    python scripts/run_codeworld.py --theme town $W $B --universes 1 2 3 4 5 --modules 24 --fns-per-module 6 --capacities 12 \
      --team-sizes 12 --projects-per-dev 3 --sprints 10 --variants solo random owners directory pooled --out "$OUT/districts$W$B"
  done
done
