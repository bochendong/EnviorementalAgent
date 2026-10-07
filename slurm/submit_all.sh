#!/bin/bash
# Submit the full study: one GPU job per (env, experiment, universe) so they run in parallel.
# Run slurm/pilot_board.sh first and check its timing and difficulty.
#   bash slurm/submit_all.sh                    # all environments, default model (Qwen3-8B)
#   ENVS=board bash slurm/submit_all.sh         # only the town board (main SeedVille setting)
#   UNIVERSES="1 2" bash slurm/submit_all.sh    # fewer universes
#   MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/submit_all.sh
#
#   board    compgen (memory conditions), library, sources, team          4 jobs per universe
#   town     compgen, persistence, law_shift, multiagent, curriculum,
#            library                                                       6 jobs per universe
#   dungeon  compgen, persistence, law_shift, multiagent, curriculum       5 jobs per universe
set -euo pipefail
cd "$(dirname "$0")/.."
source slurm/env.sh
OUT="${OUT:-$WS_STORE/results/$SERVED_NAME}"
UNIVERSES="${UNIVERSES:-0 1 2 3 4}"
REPEATS="${REPEATS:-2}"
ENVS="${ENVS:-board town dungeon}"

submit() {  # submit <name> <time> <experiment args...>
  local name=$1 time=$2
  shift 2
  sbatch --job-name="$name" --time="$time" slurm/serve_and_run.sh "$@"
}

for env in $ENVS; do
case "$env" in
  board) MAX_ACTIONS=200; MAX_TURNS=320; TIME=1-00:00 ;;  # a week of four requests
  town) MAX_ACTIONS=80; MAX_TURNS=140; TIME=0-12:00 ;;     # crops take two nights
  *) MAX_ACTIONS=50; MAX_TURNS=140; TIME=0-12:00 ;;
esac
COMMON=(--env "$env" --concurrency 32 --max-actions "$MAX_ACTIONS" --max-turns "$MAX_TURNS" --save-traces)
for u in $UNIVERSES; do
  if [ "$env" = board ]; then
    # main table: memory conditions on unseen block combinations (board episodes are long: one view)
    submit "ws-board-compgen-u$u" "$TIME" --protocol compgen \
      --conditions none trajectory retrieval seed seed_llm oracle --repeats 1 \
      --universes "$u" --n-train 16 --n-test 12 "${COMMON[@]}" --out "$OUT/board/compgen/u$u"
    # memory that lives in the world: sorted library vs one unsorted pile vs seed in the head
    submit "ws-board-library-u$u" "$TIME" --protocol compgen \
      --conditions none seed library library_flat --repeats 1 \
      --universes "$u" --n-train 16 --n-test 12 "${COMMON[@]}" --out "$OUT/board/library/u$u"
    # second-hand knowledge with controlled reliability: notes by other agents and villager testimony
    submit "ws-board-sources-u$u" "$TIME" --protocol compgen \
      --conditions none testimony library --source-errors 0 0.25 0.5 --repeats 1 \
      --universes "$u" --n-train 16 --n-test 12 "${COMMON[@]}" --out "$OUT/board/sources/u$u"
    # several agents on one board: solo / independent / library / messages / merged seeds
    submit "ws-board-team-u$u" "$TIME" --protocol team \
      --conditions seed --n-agents 3 --repeats 1 \
      --universes "$u" --n-train 18 --n-test 10 "${COMMON[@]}" --out "$OUT/board/team/u$u"
    continue
  fi
  R=(--repeats "$REPEATS")
  # H4/RQ8 + H3: compositional generalisation, all memory conditions, zoom vs flat
  submit "ws-$env-compgen-u$u" "$TIME" --protocol compgen \
    --conditions none trajectory retrieval seed seed_llm oracle --views zoom flat \
    --universes "$u" --n-train 24 --n-test 16 "${R[@]}" "${COMMON[@]}" --out "$OUT/$env/compgen/u$u"
  # H1/RQ1: persistent world vs reset
  submit "ws-$env-persist-u$u" "$TIME" --protocol persistence \
    --conditions none retrieval seed --universes "$u" --n-test 8 "${R[@]}" "${COMMON[@]}" \
    --out "$OUT/$env/persistence/u$u"
  # H5/RQ7: law shift
  submit "ws-$env-shift-u$u" "$TIME" --protocol law_shift \
    --conditions none seed --decay 0.7 --universes "$u" --n-train 16 "${R[@]}" "${COMMON[@]}" \
    --out "$OUT/$env/law_shift/u$u"
  # RQ9: shared vs independent seeds
  submit "ws-$env-multi-u$u" "$TIME" --protocol multiagent \
    --conditions seed --n-agents 4 --universes "$u" --n-train 16 --n-test 12 "${R[@]}" "${COMMON[@]}" \
    --out "$OUT/$env/multiagent/u$u"
  # RQ10: mutation curriculum vs uniform
  submit "ws-$env-curr-u$u" "$TIME" --protocol curriculum \
    --conditions seed --universes "$u" --n-train 24 --n-test 12 "${R[@]}" "${COMMON[@]}" \
    --out "$OUT/$env/curriculum/u$u"
  if [ "$env" = town ]; then
    submit "ws-town-library-u$u" "$TIME" --protocol compgen \
      --conditions none seed library library_flat --universes "$u" --n-train 24 --n-test 16 "${R[@]}" \
      "${COMMON[@]}" --out "$OUT/town/library/u$u"
  fi
done
done
echo "submitted. results -> $OUT ; summarise with: python scripts/analyze.py $OUT --curve"
