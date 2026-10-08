#!/bin/bash
#SBATCH --job-name=ws-frontier-cpu
#SBATCH --account=def-CHANGE_ME
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=0-12:00
#SBATCH --output=logs/%x-%j.out
#
# The frontier studies with the heuristic agent (no GPU, no LLM): baselines and large sweeps.
#   sbatch slurm/frontier_cpu.sh
#   UNIVERSES="1" REPEATS=1 sbatch slurm/frontier_cpu.sh
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs
source "$AGENT_VENV/bin/activate"
OUT="${OUT:-$WS_STORE/results/frontier_cpu}"
UNIVERSES="${UNIVERSES:-0 1 2 3 4}"
H=(--env board --policy heuristic --max-actions 200)
run() { python scripts/run_experiment.py "${H[@]}" "$@"; }

# science realism: one variant per directory
C=(--protocol compgen --universes $UNIVERSES --n-train 30 --n-test 16 --repeats "${REPEATS:-3}")
run "${C[@]}" --conditions none seed library --out "$OUT/realism/base"
for p in 0.1 0.25; do
  run "${C[@]}" --conditions none seed library --noise $p --out "$OUT/realism/noise$p"
  run "${C[@]}" --conditions library --noise $p --publication-bias --out "$OUT/realism/pubbias$p"
  run "${C[@]}" --conditions none seed --screen-error $p --out "$OUT/realism/screen$p"
done
run "${C[@]}" --conditions seed --confounder --out "$OUT/realism/confounder"
run "${C[@]}" --conditions seed --confounder --deconfound --out "$OUT/realism/deconfound"
run "${C[@]}" --conditions none seed --zoom-budget 4 --out "$OUT/perception"

# teams on the festival board, with and without private perception
for roles in "" --roles; do
  run --protocol team --conditions seed --n-agents 3 --universes $UNIVERSES --n-train 24 --n-test 12 \
    --repeats "${REPEATS:-3}" --festival $roles --out "$OUT/team/festival${roles:+_roles}"
done

# evolution: selection on the true score vs on claimed knowledge, then transfer to unseen universes
run --protocol evolve --universes 1 2 3 --n-train 6 --n-test 6 --noise 0.2 --evolve-generations 16 \
  --evolve-pop 16 --repeats "${REPEATS:-3}" --transfer-universes 5 6 7 8 9 --transfer-curve 1 2 4 8 \
  --out "$OUT/evolve"

# hives: correlated liars vs provenance, and a law shift (64 crops)
for u in $UNIVERSES; do
  run --protocol hive --conditions seed --n-crops 64 --hive-sizes 16 64 256 --hive-waves 12 --universes "$u" \
    --n-test 16 --hive-faulty 0.3 0.6 --hive-faulty-mode groups \
    --hive-modes sync hive_verified hive_audit hive_provenance --out "$OUT/hive/liars/u$u"
  for share in 1 0.5; do
    run --protocol hive --conditions seed --n-crops 64 --hive-sizes 16 64 --hive-waves 16 --universes "$u" \
      --n-test 16 --hive-shift-wave 6 --hive-shift-share $share --hive-modes isolated sync hive_verified hive_recent \
      --out "$OUT/hive/shift$share/u$u"
  done
done

for d in "$OUT"/realism/* "$OUT/perception"; do echo "== $d"; python scripts/analyze.py "$d" --by condition phase; done
for d in "$OUT"/team/*; do echo "== $d"; python scripts/analyze.py "$d" --by variant; done
python scripts/analyze_evolve.py "$OUT/evolve"
python scripts/analyze_hive.py "$OUT"/hive/liars
for share in 1 0.5; do python scripts/analyze_hive.py "$OUT"/hive/shift$share; done
