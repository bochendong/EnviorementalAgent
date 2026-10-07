#!/bin/bash
# Small Qwen pilot on the town board before the full study (four GPU jobs, a few hours each):
#   1. difficulty: no memory vs learned seed vs true laws. The board is well calibrated if the
#      three are clearly apart (true laws well above 0, no memory well below 1).
#   2. sources: testimony and library notes with 0% and 50% wrong claims.
#   3. team: two agents on one board, each mode of sharing.
#   4. hive: up to 4 Qwen agents in parallel towns sharing one memory (16 crops, 42 laws).
# Each job prints the summary table at the end of its log (logs/ws-pilot-*.out).
#   bash slurm/pilot_board.sh
#   MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/pilot_board.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source slurm/env.sh
OUT="${OUT:-$WS_STORE/results/$SERVED_NAME/pilot}"
COMMON=(--env board --protocol compgen --universes 1 --n-train 12 --n-test 10 --max-actions 200
        --max-turns 320 --concurrency 32 --save-traces)
sbatch --job-name=ws-pilot-difficulty --time=0-08:00 slurm/serve_and_run.sh \
  --conditions none seed oracle "${COMMON[@]}" --out "$OUT/difficulty"
sbatch --job-name=ws-pilot-sources --time=0-08:00 slurm/serve_and_run.sh \
  --conditions none testimony library --source-errors 0 0.5 "${COMMON[@]}" --out "$OUT/sources"
sbatch --job-name=ws-pilot-team --time=0-08:00 slurm/serve_and_run.sh \
  --protocol team --conditions seed --n-agents 2 --env board --universes 1 --n-train 8 --n-test 4 \
  --max-actions 200 --max-turns 320 --concurrency 32 --save-traces --out "$OUT/team"
sbatch --job-name=ws-pilot-hive --time=0-08:00 slurm/serve_and_run.sh \
  --protocol hive --conditions seed --env town --n-crops 16 --hive-sizes 1 4 --hive-waves 3 \
  --hive-modes isolated sync hive_full --hive-faulty 0 0.25 --universes 1 --n-test 4 \
  --max-actions 80 --max-turns 140 --concurrency 32 --save-traces --out "$OUT/hive"
echo "hive summary: python scripts/analyze_hive.py $OUT/hive"
echo "submitted. when done: python scripts/analyze.py $OUT/* --by protocol condition variant phase"
echo "replay an episode in the browser: python scripts/export_replay.py $OUT/sources --help"
