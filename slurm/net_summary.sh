#!/bin/bash
#SBATCH --job-name=net-summary
#SBATCH --account=def-CHANGE_ME
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=0-00:30
#SBATCH --output=logs/%x-%j.out
#
# No GPU: tabulates the runs of an experiment directory (every runs.jsonl under it, e.g. one per design)
# into summary.md and hypotheses.json, and rebuilds the run's index (slurm/run_all.sh writes both).
#   DIR=$SCRATCH/worldseeds/results/net/<run>/test sbatch slurm/net_summary.sh
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
source "$AGENT_VENV/bin/activate"
: "${DIR:?set DIR to an experiment directory}"
python -m netagents.evaluate --summarize "$DIR" || echo "no runs in $DIR yet"
python -m netagents.report "$(dirname "$DIR")" || true
