#!/bin/bash
# CodeWorld on Nibi: networks of LLM developers in a software ecosystem with hidden behaviour.
# One GPU job per world size (16, 32, 64 functions): solo with the team's compute, solo with unlimited memory,
# and teams of 4 organised by owners, a directory or random asking; notebooks of 8 and 16 laws.
#   PILOT=1 bash slurm/submit_codeworld.sh          # one small world, 2 sprints: check timing first
#   bash slurm/submit_codeworld.sh
#   MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/submit_codeworld.sh
# Heuristic sweeps (CPU, minutes): sbatch slurm/codeworld_cpu.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source slurm/env.sh
OUT="${OUT:-$WS_STORE/results/$SERVED_NAME/codeworld}"
COMMON=(--variants solo solo_unbounded owners directory random --team-sizes 4 --capacities 8 16
        --projects-per-dev 2 --budget 100 --max-turns 160 --universes ${UNIVERSES:-1 2})
if [ "${PILOT:-0}" = 1 ]; then
  sbatch --job-name=ws-codeworld-pilot --time=0-06:00 slurm/codeworld_job.sh "${COMMON[@]}" --modules 8 \
    --sprints 2 --universes 1 --out "$OUT/pilot"
  exit 0
fi
for m in ${MODULES:-4 8 16}; do
  sbatch --job-name="ws-codeworld-m$m" slurm/codeworld_job.sh "${COMMON[@]}" --modules "$m" --sprints 4 \
    --out "$OUT/m$m"
done
echo "results -> $OUT ; summary: python scripts/analyze_codeworld.py $OUT --costs"
