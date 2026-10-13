#!/bin/bash
#SBATCH --job-name=ws-town-mig-pilot
#SBATCH --account=def-hup-ab_gpu
#SBATCH --gres=gpu:nvidia_h100_80gb_hbm3_3g.40gb:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?submit from repository root}"
source slurm/env.sh
load_modules
mkdir -p logs
export PYTHONUNBUFFERED=1
export MAX_MODEL_LEN=32768
# Extra flags are appended after the defaults; argparse uses the final value.
export EXTRA_VLLM_ARGS="${EXTRA_VLLM_ARGS:-} --max-num-seqs 4"
OUT="${OUT:-$WS_STORE/results/town_mig_pilot/$SLURM_JOB_ID}"
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/commit.txt"
git diff -- slurm > "$OUT/slurm-local.patch"
cp slurm/town_mig_pilot.sh "$OUT/job.sh"
date -u +%FT%TZ > "$OUT/started-utc.txt"
START_SECONDS=$SECONDS
nvidia-smi -L
nvidia-smi -q > "$OUT/gpu-start.txt"
source slurm/start_vllm.sh
printf 'server_ready_seconds=%s\n' "$((SECONDS - START_SECONDS))" | tee "$OUT/timing.txt"
monitor_gpu() {
  while true; do
    date -u +%FT%TZ
    nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv || true
    curl -sf "http://127.0.0.1:$PORT/metrics" | grep -E '^(vllm:gpu_cache_usage_perc|vllm:kv_cache_usage_perc|vllm:num_requests_running)' || true
    sleep 15
  done
}
monitor_gpu > "$OUT/gpu-samples.log" 2>&1 &
MONITOR_PID=$!
cleanup() {
  kill "$MONITOR_PID" "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT
RUN_SECONDS=$SECONDS
set +e
python scripts/run_codeworld.py --policy llm --save-traces --theme town --walk --money --answer-price 0 \
  --goals banquet prize fund --fund 300 --goal-deadline 1 \
  --universes 1 --modules 8 --fns-per-module 6 --capacities 12 --team-sizes 4 \
  --sprints 1 --projects-per-dev 1 --budget 40 --max-turns 160 \
  --variants solo owners --out "$OUT"
RUN_EXIT=$?
set -e
printf 'experiment_seconds=%s\nexit_code=%s\n' "$((SECONDS - RUN_SECONDS))" "$RUN_EXIT" | tee -a "$OUT/timing.txt"
cp "$SERVER_LOG" "$OUT/vllm.log"
if [ "$RUN_EXIT" -eq 0 ]; then
  python scripts/analyze_codeworld.py "$OUT" --costs
fi
exit "$RUN_EXIT"
