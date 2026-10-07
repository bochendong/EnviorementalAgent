#!/bin/bash
# Submit the full study: one GPU job per (env, protocol, universe) so they run in parallel.
#   bash slurm/submit_all.sh                    # both environments, default model (Qwen3-8B)
#   ENVS=town bash slurm/submit_all.sh          # only SeedVille
#   MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/submit_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source slurm/env.sh
OUT="${OUT:-$WS_STORE/results/$SERVED_NAME}"
UNIVERSES="${UNIVERSES:-0 1 2 3 4}"
REPEATS="${REPEATS:-2}"
ENVS="${ENVS:-board town dungeon}"

for env in $ENVS; do
# the town needs a few more actions (crops take two nights); the board is a week of four requests
case "$env" in
  board) MAX_ACTIONS=200; MAX_TURNS=320 ;;
  town) MAX_ACTIONS=80; MAX_TURNS=140 ;;
  *) MAX_ACTIONS=50; MAX_TURNS=140 ;;
esac
COMMON=(--env "$env" --repeats "$REPEATS" --concurrency 32 --max-actions "$MAX_ACTIONS" --max-turns "$MAX_TURNS" --save-traces)
for u in $UNIVERSES; do
  # H4/RQ8 + H3: compositional generalisation, all memory conditions, zoom vs flat
  sbatch --job-name="ws-$env-compgen-u$u" slurm/serve_and_run.sh --protocol compgen \
    --conditions none trajectory retrieval seed seed_llm oracle --views zoom flat \
    --universes "$u" --n-train 24 --n-test 16 "${COMMON[@]}" --out "$OUT/$env/compgen/u$u"
  # H1/RQ1: persistent world vs reset
  sbatch --job-name="ws-$env-persist-u$u" slurm/serve_and_run.sh --protocol persistence \
    --conditions none retrieval seed --universes "$u" --n-test 8 "${COMMON[@]}" --out "$OUT/$env/persistence/u$u"
  # H5/RQ7: law shift
  sbatch --job-name="ws-$env-shift-u$u" slurm/serve_and_run.sh --protocol law_shift \
    --conditions none seed --decay 0.7 --universes "$u" --n-train 16 "${COMMON[@]}" --out "$OUT/$env/law_shift/u$u"
  # RQ9: shared vs independent seeds
  sbatch --job-name="ws-$env-multi-u$u" slurm/serve_and_run.sh --protocol multiagent \
    --conditions seed --n-agents 4 --universes "$u" --n-train 16 --n-test 12 "${COMMON[@]}" --out "$OUT/$env/multiagent/u$u"
  # memory that lives in the world: categorized library vs one unsorted pile vs seed in the head (town only)
  if [ "$env" != dungeon ]; then
  sbatch --job-name="ws-$env-library-u$u" slurm/serve_and_run.sh --protocol compgen \
    --conditions none seed library library_flat --universes "$u" --n-train 24 --n-test 16 "${COMMON[@]}" \
    --out "$OUT/$env/library/u$u"
  fi
  # RQ10: mutation curriculum vs uniform
  sbatch --job-name="ws-$env-curr-u$u" slurm/serve_and_run.sh --protocol curriculum \
    --conditions seed --universes "$u" --n-train 24 --n-test 12 "${COMMON[@]}" --out "$OUT/$env/curriculum/u$u"
done
done
echo "submitted. results -> $OUT ; summarise with: python scripts/analyze.py $OUT --curve"
