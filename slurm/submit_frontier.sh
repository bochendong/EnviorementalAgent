#!/bin/bash
# Submit the frontier studies (LLM agents, one GPU job each; see docs/experiments.md, "Frontier studies"):
#   bash slurm/submit_frontier.sh                      # every study, universes 1 2
#   STUDIES="context realism" bash slurm/submit_frontier.sh
#   PILOT=1 bash slurm/submit_frontier.sh              # tiny versions (one universe, few towns) to check timing
#   MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/submit_frontier.sh
#
#   context    transcript vs memory canvas (text), with and without a learned seed
#   perception zoom with a cost: 4 close looks a day
#   realism    noisy outcomes, cheap noisy screens, a weather confounder, publication bias
#   skin       the same laws told as drug discovery (compounds, targets, protocols)
#   team       compute-matched solo vs teams on the festival board, with private-perception roles
#   evolve     generations of agents with inherited playbooks, true vs self-graded selection, transfer
#   hive       correlated faulty groups vs provenance and audits; a regional law shift
# Pictures for vision-language models: bash slurm/submit_vision.sh. Heuristic (CPU) versions of the same
# studies: sbatch slurm/frontier_cpu.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source slurm/env.sh
OUT="${OUT:-$WS_STORE/results/$SERVED_NAME/frontier}"
STUDIES="${STUDIES:-context perception realism skin team evolve hive}"
UNIVERSES="${UNIVERSES:-1 2}"
TIME="${TIME:-1-00:00}"
if [ "${PILOT:-0}" = 1 ]; then
  UNIVERSES="${UNIVERSES_PILOT:-1}"; TIME=0-06:00; NTR=4; NTE=3; OUT="$OUT/pilot"
else
  NTR=12; NTE=10
fi
BOARD=(--env board --max-actions 200 --max-turns 320 --concurrency 32 --save-traces)

submit() {  # submit <name> <experiment args...>
  local name=$1
  shift
  sbatch --job-name="$name" --time="$TIME" slurm/serve_and_run.sh "$@"
}

for u in $UNIVERSES; do
  C=(--protocol compgen --universes "$u" --n-train "$NTR" --n-test "$NTE" "${BOARD[@]}")
  for study in $STUDIES; do
    case "$study" in
    context)
      for ctx in transcript canvas; do
        submit "ws-ctx-$ctx-u$u" --conditions none seed --context "$ctx" "${C[@]}" --out "$OUT/context/$ctx/u$u"
      done ;;
    perception)
      submit "ws-zoomcost-u$u" --conditions none seed --zoom-budget 4 "${C[@]}" --out "$OUT/perception/u$u" ;;
    realism)
      submit "ws-noise-u$u" --conditions none seed library --noise 0.2 "${C[@]}" --out "$OUT/realism/noise/u$u"
      submit "ws-screen-u$u" --conditions none seed --screen-error 0.2 "${C[@]}" --out "$OUT/realism/screen/u$u"
      submit "ws-confound-u$u" --conditions none seed --confounder "${C[@]}" --out "$OUT/realism/confounder/u$u"
      submit "ws-pubbias-u$u" --conditions library --noise 0.2 --publication-bias "${C[@]}" \
        --out "$OUT/realism/pubbias/u$u" ;;
    skin)
      submit "ws-drug-u$u" --conditions none seed --skin drug "${C[@]}" --out "$OUT/skin/drug/u$u" ;;
    team)
      submit "ws-festival-u$u" --protocol team --conditions seed --n-agents 3 --festival --roles \
        --team-modes solo solo_matched independent messages merged --universes "$u" \
        --n-train $((NTR + 6)) --n-test "$NTE" "${BOARD[@]}" --out "$OUT/team/festival/u$u" ;;
    evolve)
      G=4; P=4
      [ "${PILOT:-0}" = 1 ] && { G=2; P=2; }
      submit "ws-evolve-u$u" --protocol evolve --universes "$u" --n-train 2 --n-test 2 \
        --evolve-generations "$G" --evolve-pop "$P" --evolve-archive 3 --transfer-universes 7 --transfer-curve 1 2 \
        "${BOARD[@]}" --out "$OUT/evolve/u$u" ;;
    hive)
      H=(--protocol hive --conditions seed --env town --n-crops 16 --hive-sizes 8 --hive-waves 6 --universes "$u"
         --n-test 4 --max-actions 80 --max-turns 140 --concurrency 32 --save-traces)
      submit "ws-hive-liars-u$u" "${H[@]}" --hive-modes sync hive_verified hive_audit hive_provenance \
        --hive-faulty 0.5 --hive-faulty-mode groups --out "$OUT/hive/liars/u$u"
      submit "ws-hive-shift-u$u" "${H[@]}" --hive-modes sync hive_verified hive_recent \
        --hive-shift-wave 3 --hive-shift-share 1 --out "$OUT/hive/shift/u$u" ;;
    *) echo "unknown study $study" >&2; exit 1 ;;
    esac
  done
done
echo "submitted. results -> $OUT"
echo "summaries: python scripts/analyze.py $OUT/{context,perception,realism,skin} --by condition context phase"
echo "           python scripts/analyze.py $OUT/team --by variant ; python scripts/analyze_evolve.py $OUT/evolve"
echo "           python scripts/analyze_hive.py $OUT/hive/liars ; python scripts/analyze_hive.py $OUT/hive/shift"
